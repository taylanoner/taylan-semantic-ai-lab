"""Week 13: Model A (poor metadata) vs Model B (AI-ready metadata), same
governed mart schema, dev set only (24 in-scope + 4 out-of-scope).

This does NOT use Fabric's Data Agent/Copilot (blocked on an Azure billing
tenant issue this week) -- it simulates the same comparison by varying how
much business metadata surrounds an identical governed schema in the system
prompt, using the Claude API directly. Same governed SQL surface (the dbt
marts) in both configurations; only the documentation quality differs.

Usage:
    python src/run_metadata_ab.py
"""

import csv
import json
import re
import sys

import duckdb
import yaml

from llm_client import MODEL, extract_text, get_client

WAREHOUSE = "warehouse.duckdb"
DEV_QUESTIONS = "evals/dev.yaml"
DEV_OOS_QUESTIONS = "evals/dev_out_of_scope.yaml"
OUT_CSV = "reports/metadata-ab-dev.csv"

MART_TABLES = [
    "dim_customers", "dim_date", "fct_transactions",
    "fct_account_balances_monthly", "fct_loans_monthly", "fct_interest_monthly",
]

# --- Model A: poor metadata -- table/column names and types only ----------

def build_schema_a(con: duckdb.DuckDBPyConnection) -> str:
    lines = []
    for t in MART_TABLES:
        lines.append(f"TABLE {t}")
        for col, dtype, *_ in con.execute(f"DESCRIBE {t}").fetchall():
            lines.append(f"  {col} {dtype}")
    return "\n".join(lines)


SYSTEM_PROMPT_A = """You are a SQL assistant for a banking analytics warehouse.
Schema:
{schema}

Write a single DuckDB SQL query that answers the user's question using only
the tables/columns above. Output ONLY the SQL query, nothing else. If the
question cannot be answered using this schema, output exactly: CANNOT_ANSWER
"""

# --- Model B: AI-ready metadata -- descriptions, metric defs, synonyms,
# verified answers (from the dev set only), explicit scope + refusal rule --

TABLE_DESCRIPTIONS = {
    "dim_customers": "Customer dimension. is_active reflects behavioral recency (a transaction in the trailing 90 days), NOT account status.",
    "dim_date": "Calendar dimension, one row per day.",
    "fct_transactions": (
        "Governed transaction fact -- internal accounts already excluded and reversed "
        "transaction pairs already netted out (do not filter for these yourself, it's "
        "already done). transaction_date is when the customer acted; posting_date is when "
        "it hit the ledger -- use transaction_date unless the question is explicitly about "
        "ledger/period-close timing. home_branch_name is the customer's registered branch "
        "(use this for branch performance questions); transaction_branch_name is where the "
        "transaction physically happened (use only for foot-traffic questions)."
    ),
    "fct_account_balances_monthly": (
        "One row per account per month. avg_daily_balance is the mean balance across the "
        "whole month; month_end_balance is a single point-in-time snapshot on the last day. "
        "These are two different, valid numbers -- pick based on what the question asks."
    ),
    "fct_loans_monthly": (
        "One row per loan per month. write_off_flag marks loans moved to charge-off. "
        "Delinquency-rate style questions should EXCLUDE write_off_flag=true loans from "
        "the denominator (they're no longer part of the active book); charge-off questions "
        "should count write_off_flag=true loans directly instead."
    ),
    "fct_interest_monthly": (
        "One row per account per month. interest_income is from loans, interest_expense is "
        "paid on deposits (mutually exclusive per row). Net interest income = "
        "SUM(interest_income) - SUM(interest_expense)."
    ),
}

METRIC_DEFINITIONS = """Governed metric definitions (use these exact definitions, don't improvise):
- Net fee revenue: -SUM(amount) WHERE transaction_type='fee' AND fee_waived=FALSE (excludes waived fees)
- Transaction volume: SUM(ABS(amount)) over fct_transactions (already governed, no extra filtering needed)
- Average daily balance: AVG(avg_daily_balance) over fct_account_balances_monthly
- Active customer count: COUNT(*) WHERE is_active=TRUE over dim_customers
- Customer inactivity rate: COUNT(is_active=FALSE) / COUNT(*) over dim_customers
- Delinquency rate 30D/90D: COUNT(days_past_due>=30 or 90) / COUNT(*), both filtered to write_off_flag=FALSE, over the latest record per loan per period
- Charge-off rate: COUNT(write_off_flag=TRUE) / COUNT(*) over fct_loans_monthly
- Net interest income: SUM(interest_income) - SUM(interest_expense) over fct_interest_monthly
- Net interest margin: Net interest income / SUM(outstanding_loan_balance)"""

SYNONYMS = """Synonyms:
- "revenue" / "income" (fee context) -> net fee revenue (unless the question explicitly says "gross")
- "active" (customer context) -> behavioral (is_active flag), NOT account status
- "balance" without qualification -> ask yourself: does the question want a period average or a point-in-time snapshot? Both exist as separate columns.
- "written off" / "charged off" -> write_off_flag=TRUE
- "branch" without qualification -> customer's home branch (home_branch_name), not the transaction location"""

VERIFIED_ANSWERS = """Verified example (from the approved training set -- follow this exact pattern for similar questions):
Q: "How many active customers do we have in the GTA-West region?"
A: SELECT COUNT(*) FROM dim_customers WHERE is_active = TRUE AND region = 'GTA-West'"""

SCOPE_RULE = """Scope: only answer questions that can be computed from the tables and metric
definitions above. If the question asks for something not represented here
(predictive/ML scores, external/competitor data, a dimension that doesn't
exist, data outside this domain), output exactly: CANNOT_ANSWER -- do not
guess or approximate."""


def build_schema_b(con: duckdb.DuckDBPyConnection) -> str:
    lines = []
    for t in MART_TABLES:
        lines.append(f"TABLE {t} -- {TABLE_DESCRIPTIONS[t]}")
        for col, dtype, *_ in con.execute(f"DESCRIBE {t}").fetchall():
            lines.append(f"  {col} {dtype}")
    return "\n".join(lines)


SYSTEM_PROMPT_B = """You are a SQL assistant for a banking analytics warehouse.
Schema:
{schema}

{metrics}

{synonyms}

{verified}

{scope}

Write a single DuckDB SQL query that answers the user's question. Output ONLY
the SQL query, nothing else, unless the scope rule above applies.
"""


def load_questions() -> list:
    with open(DEV_QUESTIONS, encoding="utf-8") as f:
        dev = yaml.safe_load(f)
    with open(DEV_OOS_QUESTIONS, encoding="utf-8") as f:
        oos = yaml.safe_load(f)
    return dev + oos


def extract_sql(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(sql)?", "", text).strip()
        text = text.rstrip("`").strip()
    return text


def run_one(client, system_prompt: str, question: dict, con: duckdb.DuckDBPyConnection) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": question["question"]}],
    )
    raw_text = extract_text(response).strip()

    if "CANNOT_ANSWER" in raw_text.upper():
        if question["answerable"]:
            return {"result": None, "category": "inappropriate_refusal", "sql": None}
        return {"result": None, "category": "appropriate_refusal", "sql": None}

    sql = extract_sql(raw_text)
    try:
        row = con.execute(sql).fetchone()
        value = row[0] if row else None
    except Exception as exc:
        return {"result": None, "category": "invalid_sql", "sql": sql, "error": str(exc)}

    if not question["answerable"]:
        return {"result": value, "category": "answered_unanswerable", "sql": sql}

    if value is None:
        return {"result": None, "category": "null_result", "sql": sql}

    expected = question["expected_result"]
    if isinstance(expected, (int, float)) and abs(float(value) - expected) < max(0.01, abs(expected) * 0.001):
        return {"result": float(value), "category": "correct", "sql": sql}
    return {"result": float(value) if isinstance(value, (int, float)) else value, "category": "wrong_result", "sql": sql}


def main() -> None:
    con = duckdb.connect(WAREHOUSE, read_only=True)
    client = get_client()

    schema_a = build_schema_a(con)
    schema_b = build_schema_b(con)
    system_a = SYSTEM_PROMPT_A.format(schema=schema_a)
    system_b = SYSTEM_PROMPT_B.format(
        schema=schema_b, metrics=METRIC_DEFINITIONS, synonyms=SYNONYMS,
        verified=VERIFIED_ANSWERS, scope=SCOPE_RULE,
    )

    questions = load_questions()
    rows = []
    total = len(questions) * 2
    i = 0
    for q in questions:
        for model_name, system_prompt in [("A_poor_metadata", system_a), ("B_ai_ready", system_b)]:
            i += 1
            print(f"[{i}/{total}] {q['id']} ({model_name})...", end=" ", flush=True)
            try:
                result = run_one(client, system_prompt, q, con)
            except Exception as exc:
                result = {"result": None, "category": "api_error", "sql": None, "error": str(exc)}
            print(result["category"])
            rows.append({
                "question_id": q["id"],
                "model": model_name,
                "answerable_expected": q["answerable"],
                "category": result["category"],
                "model_result": result.get("result"),
                "expected_result": q.get("expected_result"),
                "sql": result.get("sql"),
            })

    con.close()

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} rows to {OUT_CSV}")


if __name__ == "__main__":
    sys.exit(main())
