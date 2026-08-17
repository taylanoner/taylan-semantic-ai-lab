"""Week 13: Model A (poor metadata) vs Model B (AI-ready) on the governed
schema.

Both models query the SAME governed dbt marts (dim_customers, fct_transactions,
etc.) -- the variable under test is ONLY the metadata layer, not the
underlying governance (that comparison already happened in Week 6/16).

Model A: technical column names, no descriptions, no synonyms, no verified
answers, no scope guidance.
Model B: business names (already true of the marts), full descriptions,
synonyms per ambiguity, verified answers FROM THE DEV SET ONLY, explicit
scope + refusal guidance.

Runs against evals/dev.yaml + evals/dev_out_of_scope.yaml only. Does NOT
touch the sealed held-out sets. Uses Claude directly (no Fabric/Azure spend).

Usage:
    python src/run_metadata_ab.py
"""

import csv
import os
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
    "dim_customers", "fct_transactions", "fct_account_balances_monthly",
    "fct_loans_monthly", "fct_interest_monthly",
]

AMBIGUITY_TO_CATEGORY = {
    "gross_vs_net_revenue": "wrong_metric",
    "posting_vs_transaction_date": "wrong_date",
    "open_vs_active_account": "wrong_filter",
    "month_end_vs_avg_daily_balance": "wrong_metric",
    "written_off_loans": "wrong_filter",
    "reversed_transactions": "wrong_filter",
    "internal_accounts": "wrong_filter",
    "customer_vs_branch_location": "wrong_join",
}

MODEL_A_TEMPLATE = """You are a SQL assistant for a DuckDB database. Given the schema \
below, write a single SQL query that answers the user's question.

Schema:
{ddl}

Rules:
- Output ONLY the SQL query. No markdown fences, no commentary.
- If the question cannot be answered using this schema, output exactly: CANNOT_ANSWER
"""

MODEL_B_TEMPLATE = """You are a SQL assistant for a governed banking analytics warehouse \
(DuckDB). Given the schema, descriptions, synonyms, and verified examples below, write a \
single SQL query that answers the user's question.

Schema and descriptions:
{ddl_with_descriptions}

Synonyms (these terms are equivalent to the column/concept named):
- "revenue", "income", "earnings" (in a fee context) -> net fee revenue: fct_transactions \
where transaction_type='fee' AND fee_waived=FALSE
- "active" (for a customer) -> dim_customers.is_active = TRUE (behavioral, NOT account status)
- "balance" without qualification -> ask yourself: month-end snapshot or period average? Use \
fct_account_balances_monthly.avg_daily_balance for "average"/"typical" balance, \
month_end_balance for "as of" / snapshot balance.
- "written off", "charged off" -> fct_loans_monthly.write_off_flag = TRUE
- "branch" without qualification -> use home_branch_name (the customer's registered branch) \
for performance/relationship reporting; only use transaction_branch_name if the question is \
explicitly about where a transaction physically occurred.
- "posted" / "settled" -> posting_date; "initiated" / "made" (by the customer) -> transaction_date

Verified examples (question -> correct SQL), drawn only from the open dev set:
{verified_examples}

Scope: this warehouse covers customer, transaction, deposit balance, loan delinquency, and \
interest data as shown in the schema above. It does NOT contain: predictive/ML scores, \
regulatory capital metrics, competitor data, sales-rep or employee/HR data, or any dimension \
not listed in the schema.

Rules:
- Output ONLY the SQL query. No markdown fences, no commentary.
- If the question falls outside the scope described above, or requires data/capabilities not \
in this schema, output exactly: CANNOT_ANSWER
"""


def build_ddl(con: duckdb.DuckDBPyConnection, with_descriptions: bool) -> str:
    descriptions = {
        "dim_customers": "Customer dimension.",
        "fct_transactions": "Governed transaction fact -- internal accounts already excluded, reversals already netted.",
        "fct_account_balances_monthly": "One row per account per month. avg_daily_balance = mean across the month (typical balance). month_end_balance = snapshot on the last day (point-in-time).",
        "fct_loans_monthly": "One row per loan per month, most recent days_past_due. write_off_flag marks loans moved to charge-off, excluded from active-portfolio delinquency.",
        "fct_interest_monthly": "One row per account per month. interest_income (loans) and interest_expense (deposits) are mutually exclusive per row.",
    }
    col_notes = {
        "is_active": "behavioral: had a transaction in the trailing 90 days -- NOT the same as account status",
        "transaction_date": "when the customer initiated the transaction",
        "posting_date": "when the transaction settled to the ledger (0-3 days later)",
        "home_branch_name": "the customer's registered/relationship branch",
        "transaction_branch_name": "the branch where this specific transaction physically occurred",
        "avg_daily_balance": "average of daily balances across the month",
        "month_end_balance": "balance snapshot on the last day of the month",
        "write_off_flag": "TRUE if this loan has been charged off (excluded from active-portfolio delinquency)",
        "fee_waived": "TRUE if this fee was waived (excluded from net fee revenue)",
    }
    blocks = []
    for table in MART_TABLES:
        cols = con.execute(f"""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = '{table}' ORDER BY ordinal_position
        """).fetchall()
        if with_descriptions:
            col_lines = []
            for name, dtype in cols:
                note = f"  -- {col_notes[name]}" if name in col_notes else ""
                col_lines.append(f"    {name} {dtype}{note}")
            header = f"TABLE {table}  -- {descriptions[table]}"
            blocks.append(header + "\n" + "\n".join(col_lines))
        else:
            col_str = ", ".join(f"{name} {dtype}" for name, dtype in cols)
            blocks.append(f"TABLE {table} ({col_str})")
    return "\n\n".join(blocks)


def build_verified_examples(dev_questions: list) -> str:
    """One example per ambiguity, drawn only from the open dev set."""
    seen_tags = set()
    lines = []
    for q in dev_questions:
        tag = q.get("ambiguity_tag")
        if not tag or tag in seen_tags:
            continue
        seen_tags.add(tag)
        sql = q["sql"].strip().replace("\n", " ")
        sql = re.sub(r"\s+", " ", sql)
        lines.append(f'Q: "{q["question"]}"\nSQL: {sql}\n')
    return "\n".join(lines)


def load_questions() -> list:
    with open(DEV_QUESTIONS, encoding="utf-8") as f:
        in_scope = yaml.safe_load(f)
    with open(DEV_OOS_QUESTIONS, encoding="utf-8") as f:
        out_of_scope = yaml.safe_load(f)
    return in_scope + out_of_scope, in_scope


def extract_sql_or_refusal(raw_text: str):
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("sql"):
            text = text[3:]
        text = text.strip()
    if re.fullmatch(r"CANNOT_ANSWER\.?", text.strip(), re.IGNORECASE):
        return None, True
    return text, False


def is_close(actual: float, expected: float) -> bool:
    tolerance = max(0.01, abs(expected) * 0.01)
    return abs(actual - expected) <= tolerance


def classify(question: dict, refused: bool, exec_error: str, result_rows) -> tuple:
    answerable = question["answerable"]
    if not answerable:
        if refused:
            return "appropriate_refusal", None
        return "answered_unanswerable", (result_rows[0][0] if result_rows else None)

    if refused:
        return "inappropriate_refusal", None
    if exec_error:
        return "invalid_sql", None
    if result_rows is None or len(result_rows) != 1 or len(result_rows[0]) != 1:
        return "wrong_grain", None

    value = result_rows[0][0]
    if value is None:
        return "wrong_filter", None
    value = float(value)
    if is_close(value, question["expected_result"]):
        return "correct", value

    category = AMBIGUITY_TO_CATEGORY.get(question["ambiguity_tag"], "correct_looking_wrong_number")
    return category, value


def run_one(client, system_prompt: str, question: dict, con: duckdb.DuckDBPyConnection) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": question["question"]}],
    )
    raw_text = extract_text(response)
    sql, refused = extract_sql_or_refusal(raw_text)

    exec_error = None
    result_rows = None
    if not refused:
        try:
            result_rows = con.execute(sql).fetchall()
        except duckdb.Error as exc:
            exec_error = str(exc)

    failure_category, model_result = classify(question, refused, exec_error, result_rows)

    return {
        "question_id": question["id"],
        "answerable_expected": question["answerable"],
        "ambiguity_tag": question.get("ambiguity_tag") or "",
        "generated_sql": (sql or "").replace("\n", " ").strip(),
        "refused": refused,
        "execution_error": exec_error or "",
        "model_result": model_result,
        "expected_result": question.get("expected_result"),
        "failure_category": failure_category,
    }


def main() -> int:
    os.makedirs("reports", exist_ok=True)

    client = get_client()
    con = duckdb.connect(WAREHOUSE, read_only=True)

    questions, dev_in_scope = load_questions()

    ddl_plain = build_ddl(con, with_descriptions=False)
    ddl_rich = build_ddl(con, with_descriptions=True)
    verified_examples = build_verified_examples(dev_in_scope)

    system_prompt_a = MODEL_A_TEMPLATE.format(ddl=ddl_plain)
    system_prompt_b = MODEL_B_TEMPLATE.format(
        ddl_with_descriptions=ddl_rich, verified_examples=verified_examples
    )

    fieldnames = [
        "model", "question_id", "answerable_expected", "ambiguity_tag",
        "generated_sql", "refused", "execution_error", "model_result",
        "expected_result", "failure_category",
    ]

    rows = []
    total = len(questions) * 2
    done = 0
    for model_label, system_prompt in [("A_poor_metadata", system_prompt_a), ("B_ai_ready", system_prompt_b)]:
        for question in questions:
            row = run_one(client, system_prompt, question, con)
            row["model"] = model_label
            rows.append(row)
            done += 1
            print(f"[{done}/{total}] {model_label} {question['id']}: {row['failure_category']}")

    con.close()

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"\nWrote {len(rows)} rows to {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
