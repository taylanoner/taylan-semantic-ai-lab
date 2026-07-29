"""Week 6 build: the raw text-to-SQL baseline (built badly on purpose).

Feeds the model raw DDL + column names + the question -- no semantic layer,
no glossary, no business definitions. Lets it write its own SQL, runs it
against the warehouse, and classifies every result. This is deliberately the
worst-case configuration; later weeks build the governed alternative.

Runs ONLY the dev sets (24 in-scope + 4 out-of-scope), 3 runs each. Does NOT
touch evals/holdout.yaml or evals/out_of_scope.yaml -- the raw-schema
baseline against the held-out sets happens for the first time in week 16.

Usage:
    python src/run_baseline.py
"""

import csv
import re
import sys

import duckdb
import yaml

from llm_client import MODEL, extract_text, get_client

WAREHOUSE = "warehouse.duckdb"
DEV_QUESTIONS = "evals/dev.yaml"
DEV_OOS_QUESTIONS = "evals/dev_out_of_scope.yaml"
OUT_CSV = "reports/baseline-dev.csv"
N_RUNS = 3

# Ambiguity -> most-likely failure mode when the model gets it wrong, based on
# docs/ambiguity-register.md (e.g. picking the wrong date field IS a wrong_date
# error; picking the wrong branch join IS a wrong_join error).
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

TABLES = [
    "dim_date", "dim_branch", "dim_product", "dim_customer", "dim_account",
    "fact_transaction", "fact_daily_balance", "fact_loan_payment",
]

SYSTEM_PROMPT_TEMPLATE = """You are a SQL assistant for a DuckDB database. Given the raw \
schema below, write a single SQL query that answers the user's question.

Schema:
{ddl}

Rules:
- Output ONLY the SQL query. No markdown fences, no commentary.
- If the question cannot be answered using this schema (e.g. it requires data or a \
predictive capability this schema doesn't have), output exactly: CANNOT_ANSWER
"""


def build_raw_ddl(con: duckdb.DuckDBPyConnection) -> str:
    blocks = []
    for table in TABLES:
        cols = con.execute(f"""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = '{table}' ORDER BY ordinal_position
        """).fetchall()
        col_str = ", ".join(f"{name} {dtype}" for name, dtype in cols)
        blocks.append(f"TABLE {table} ({col_str})")
    return "\n".join(blocks)


def load_questions() -> list:
    with open(DEV_QUESTIONS, encoding="utf-8") as f:
        in_scope = yaml.safe_load(f)
    with open(DEV_OOS_QUESTIONS, encoding="utf-8") as f:
        out_of_scope = yaml.safe_load(f)
    return in_scope + out_of_scope


def extract_sql_or_refusal(raw_text: str) -> tuple:
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
    """Returns (failure_category, model_result)."""
    answerable = question["answerable"]

    if not answerable:
        if refused:
            return "appropriate_refusal", None
        return "answered_unanswerable", (result_rows[0][0] if result_rows else None)

    # answerable (in-scope) question from here on
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
    import os
    os.makedirs("reports", exist_ok=True)

    client = get_client()
    warehouse_con = duckdb.connect(WAREHOUSE, read_only=True)
    ddl = build_raw_ddl(warehouse_con)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(ddl=ddl)

    questions = load_questions()
    fieldnames = [
        "question_id", "run", "answerable_expected", "ambiguity_tag",
        "generated_sql", "refused", "execution_error", "model_result",
        "expected_result", "failure_category",
    ]

    rows = []
    total = len(questions) * N_RUNS
    done = 0
    for question in questions:
        for run in range(1, N_RUNS + 1):
            row = run_one(client, system_prompt, question, warehouse_con)
            row["run"] = run
            rows.append(row)
            done += 1
            print(f"[{done}/{total}] {question['id']} run {run}: {row['failure_category']}")

    warehouse_con.close()

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"\nWrote {len(rows)} rows to {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
