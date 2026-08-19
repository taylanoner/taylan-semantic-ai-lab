"""Week 16: the benchmark. Sealed held-out sets opened for the first time.

Four configurations x {dev, held-out} x {in-scope, out-of-scope}, 3 runs each,
against the SAME warehouse.duckdb (raw tables and governed dbt marts both
live in this one file). Configurations only vary metadata/glossary given to
the model -- the underlying data and question sets are held constant.

1. raw              -- raw schema, no glossary (= the Week 6 baseline, now
                        also run against held-out for the first time)
2. raw_glossary     -- raw schema + a business glossary (NEW for week 16)
3. governed         -- governed dbt marts, plain/technical metadata
                        (= Week 13 Model A)
4. governed_ai_prep -- governed dbt marts + full AI-ready metadata, synonyms,
                        verified examples from the dev set only
                        (= Week 13 Model B)

Usage:
    python src/run_benchmark.py
"""

import csv
import os
import re
import sys

import duckdb
import yaml

from llm_client import MODEL, extract_text, get_client

WAREHOUSE = "warehouse.duckdb"
N_RUNS = 3
RAW_CSV = "reports/benchmark-raw-results.csv"
SUMMARY_CSV = "reports/benchmark.csv"

RAW_TABLES = [
    "dim_date", "dim_branch", "dim_product", "dim_customer", "dim_account",
    "fact_transaction", "fact_daily_balance", "fact_loan_payment",
]
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

# ---------------------------------------------------------------- Config 1: raw

RAW_TEMPLATE = """You are a SQL assistant for a DuckDB database. Given the raw \
schema below, write a single SQL query that answers the user's question.

Schema:
{ddl}

Rules:
- Output ONLY the SQL query. No markdown fences, no commentary.
- If the question cannot be answered using this schema (e.g. it requires data or a \
predictive capability this schema doesn't have), output exactly: CANNOT_ANSWER
"""

# ---------------------------------------------------------- Config 2: raw + glossary

RAW_GLOSSARY_TEMPLATE = """You are a SQL assistant for a DuckDB database. Given the raw \
schema and business glossary below, write a single SQL query that answers the user's \
question.

Schema:
{ddl}

Business glossary:
- "revenue", "income", "earnings" (fee context) -> net fee revenue: \
fact_transaction WHERE transaction_type='fee' AND fee_waived=FALSE AND is_reversal=FALSE. \
The amount column stores fees as negative numbers -- negate the sum.
- "gross" fee revenue -> same as above but WITHOUT the fee_waived filter (waivers not \
excluded).
- "active" customer -> dim_customer.is_active = TRUE (behavioral: recent transaction \
activity). This is NOT the same as an account's open/closed status.
- customers with an "open account" -> dim_account.status = 'open' (structural reading).
- "balance" without qualification: "average"/"typical" balance -> AVG(balance_amount) \
across the period from fact_daily_balance. "as of [date]" / snapshot balance -> the single \
balance_amount row for that balance_date.
- "written off" / "charged off" (loans) -> dim_account.write_off_flag = TRUE.
- delinquency / days past due -> fact_loan_payment.days_past_due, most recent payment \
row per loan_account_id, EXCLUDING accounts where write_off_flag = TRUE.
- "posted" / "settled" -> posting_date. "initiated" / "made" (by the customer) -> \
transaction_date.
- reversed transactions -> fact_transaction.is_reversal / reversal_of_transaction_id. \
Net transaction volume nets reversal pairs to zero unless the question explicitly asks \
for the figure "without netting out" reversals.
- "branch" without qualification -> the customer's home branch (dim_account.home_branch_id), \
not the branch where a specific transaction physically occurred \
(fact_transaction.branch_id) -- use the transaction branch only if the question explicitly \
asks where a transaction happened.
- internal/GL accounts (dim_account.is_internal = TRUE) are excluded from customer \
activity reporting by default, unless the question explicitly asks to include them.

Rules:
- Output ONLY the SQL query. No markdown fences, no commentary.
- If the question falls outside what this schema and glossary cover, output exactly: \
CANNOT_ANSWER
"""

# ------------------------------------------------------------- Config 3/4: governed

GOVERNED_TEMPLATE = """You are a SQL assistant for a governed banking analytics warehouse \
(DuckDB). Given the schema below, write a single SQL query that answers the user's question.

Schema:
{ddl}

Rules:
- Output ONLY the SQL query. No markdown fences, no commentary.
- If the question cannot be answered using this schema, output exactly: CANNOT_ANSWER
"""

GOVERNED_AI_PREP_TEMPLATE = """You are a SQL assistant for a governed banking analytics \
warehouse (DuckDB). Given the schema, descriptions, synonyms, and verified examples below, \
write a single SQL query that answers the user's question.

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


def build_raw_ddl(con: duckdb.DuckDBPyConnection) -> str:
    blocks = []
    for table in RAW_TABLES:
        cols = con.execute(f"""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = '{table}' ORDER BY ordinal_position
        """).fetchall()
        col_str = ", ".join(f"{name} {dtype}" for name, dtype in cols)
        blocks.append(f"TABLE {table} ({col_str})")
    return "\n".join(blocks)


def build_mart_ddl(con: duckdb.DuckDBPyConnection, with_descriptions: bool) -> str:
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


def build_verified_examples(dev_in_scope: list) -> str:
    """One example per ambiguity, drawn only from the open dev set."""
    seen_tags = set()
    lines = []
    for q in dev_in_scope:
        tag = q.get("ambiguity_tag")
        if not tag or tag in seen_tags:
            continue
        seen_tags.add(tag)
        sql = q["sql"].strip().replace("\n", " ")
        sql = re.sub(r"\s+", " ", sql)
        lines.append(f'Q: "{q["question"]}"\nSQL: {sql}\n')
    return "\n".join(lines)


def load_yaml(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


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


def summarize(rows: list) -> list:
    """One row per config: dev accuracy, held-out in-scope accuracy, held-out
    out-of-scope refusal rate -- each averaged across the 3 runs."""
    configs = sorted(set(r["config"] for r in rows))
    summary = []
    for config in configs:
        crows = [r for r in rows if r["config"] == config]

        dev_in = [r for r in crows if r["question_set"] == "dev_in"]
        dev_acc = sum(1 for r in dev_in if r["failure_category"] == "correct") / len(dev_in)

        ho_in = [r for r in crows if r["question_set"] == "holdout_in"]
        ho_acc = sum(1 for r in ho_in if r["failure_category"] == "correct") / len(ho_in)

        ho_oos = [r for r in crows if r["question_set"] == "holdout_oos"]
        ho_refusal = sum(1 for r in ho_oos if r["failure_category"] == "appropriate_refusal") / len(ho_oos)

        summary.append({
            "config": config,
            "dev_in_scope_accuracy": round(dev_acc, 4),
            "holdout_in_scope_accuracy": round(ho_acc, 4),
            "holdout_out_of_scope_refusal_rate": round(ho_refusal, 4),
            "n_dev_in_runs": len(dev_in),
            "n_holdout_in_runs": len(ho_in),
            "n_holdout_oos_runs": len(ho_oos),
        })
    return summary


def main() -> int:
    os.makedirs("reports", exist_ok=True)

    client = get_client()
    con = duckdb.connect(WAREHOUSE, read_only=True)

    dev_in = load_yaml("evals/dev.yaml")
    dev_oos = load_yaml("evals/dev_out_of_scope.yaml")
    holdout_in = load_yaml("evals/holdout.yaml")
    holdout_oos = load_yaml("evals/out_of_scope.yaml")

    raw_ddl = build_raw_ddl(con)
    mart_ddl_plain = build_mart_ddl(con, with_descriptions=False)
    mart_ddl_rich = build_mart_ddl(con, with_descriptions=True)
    verified_examples = build_verified_examples(dev_in)

    configs = {
        "1_raw": RAW_TEMPLATE.format(ddl=raw_ddl),
        "2_raw_glossary": RAW_GLOSSARY_TEMPLATE.format(ddl=raw_ddl),
        "3_governed": GOVERNED_TEMPLATE.format(ddl=mart_ddl_plain),
        "4_governed_ai_prep": GOVERNED_AI_PREP_TEMPLATE.format(
            ddl_with_descriptions=mart_ddl_rich, verified_examples=verified_examples
        ),
    }

    question_sets = {
        "dev_in": dev_in,
        "dev_oos": dev_oos,
        "holdout_in": holdout_in,
        "holdout_oos": holdout_oos,
    }

    fieldnames = [
        "config", "question_set", "run", "question_id", "answerable_expected",
        "ambiguity_tag", "generated_sql", "refused", "execution_error",
        "model_result", "expected_result", "failure_category",
    ]

    rows = []
    total = sum(len(v) for v in question_sets.values()) * len(configs) * N_RUNS
    done = 0
    for config_name, system_prompt in configs.items():
        for set_name, questions in question_sets.items():
            for question in questions:
                for run in range(1, N_RUNS + 1):
                    row = run_one(client, system_prompt, question, con)
                    row["config"] = config_name
                    row["question_set"] = set_name
                    row["run"] = run
                    rows.append(row)
                    done += 1
                    print(f"[{done}/{total}] {config_name} {set_name} {question['id']} run{run}: {row['failure_category']}")

    con.close()

    with open(RAW_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"\nWrote {len(rows)} rows to {RAW_CSV}")

    summary = summarize(rows)
    with open(SUMMARY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        for row in summary:
            writer.writerow(row)
    print(f"Wrote {len(summary)} rows to {SUMMARY_CSV}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
