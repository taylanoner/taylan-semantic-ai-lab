"""Generator for the OPEN dev eval sets (evals/dev.yaml, evals/dev_out_of_scope.yaml).

Unlike scripts/generate_holdout_questions.py, these are NOT sealed -- they can
be regenerated freely while tuning metrics, synonyms, and curator instructions
through weeks 6-15.

Usage:
    python scripts/generate_dev_questions.py
"""

import yaml
import duckdb

WAREHOUSE = "warehouse.duckdb"
OUT_DEV = "evals/dev.yaml"
OUT_DEV_OOS = "evals/dev_out_of_scope.yaml"

# --- 24 dev in-scope questions, 3 per ambiguity ---------------------------

IN_SCOPE_QUESTIONS = [
    # Ambiguity 1: gross vs net revenue
    {
        "id": "dev-01",
        "ambiguity_tag": "gross_vs_net_revenue",
        "question": "What was our total net fee revenue in Q1 2026?",
        "sql": """
            SELECT ROUND(-SUM(amount), 2) FROM fact_transaction
            WHERE transaction_type = 'fee' AND fee_waived = FALSE AND is_reversal = FALSE
              AND date_part('year', transaction_date) = 2026 AND date_part('quarter', transaction_date) = 1
        """,
        "business_definition": "Net fee revenue excludes waived fees.",
    },
    {
        "id": "dev-02",
        "ambiguity_tag": "gross_vs_net_revenue",
        "question": "What was our total gross fee revenue (before waivers) in 2025?",
        "sql": """
            SELECT ROUND(-SUM(amount), 2) FROM fact_transaction
            WHERE transaction_type = 'fee' AND is_reversal = FALSE
              AND date_part('year', transaction_date) = 2025
        """,
        "business_definition": "Explicit 'gross' means before waivers are excluded -- tests that the model follows explicit user intent rather than always defaulting to net.",
    },
    {
        "id": "dev-03",
        "ambiguity_tag": "gross_vs_net_revenue",
        "question": "What was total net fee revenue from Chequing and Savings accounts in 2024?",
        "sql": """
            SELECT ROUND(-SUM(t.amount), 2) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            JOIN dim_product p ON a.product_id = p.product_id
            WHERE p.product_name IN ('Chequing', 'Savings') AND t.transaction_type = 'fee'
              AND t.fee_waived = FALSE AND t.is_reversal = FALSE
              AND date_part('year', t.transaction_date) = 2024
        """,
        "business_definition": "Net fee revenue excludes waived fees, scoped to deposit products.",
    },
    # Ambiguity 2: posting vs transaction date
    {
        "id": "dev-04",
        "ambiguity_tag": "posting_vs_transaction_date",
        "question": "How many transactions posted to the ledger in Q1 2025?",
        "sql": """
            SELECT COUNT(*) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            WHERE a.is_internal = FALSE
              AND date_part('year', t.posting_date) = 2025 AND date_part('quarter', t.posting_date) = 1
        """,
        "business_definition": "Ledger/period-close reporting uses posting_date.",
    },
    {
        "id": "dev-05",
        "ambiguity_tag": "posting_vs_transaction_date",
        "question": "How many transactions did customers initiate in Q1 2025?",
        "sql": """
            SELECT COUNT(*) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            WHERE a.is_internal = FALSE
              AND date_part('year', t.transaction_date) = 2025 AND date_part('quarter', t.transaction_date) = 1
        """,
        "business_definition": "Customer-activity reporting uses transaction_date.",
    },
    {
        "id": "dev-06",
        "ambiguity_tag": "posting_vs_transaction_date",
        "question": "What was total transaction volume in Q3 2025, based on transaction date?",
        "sql": """
            SELECT ROUND(SUM(ABS(t.amount)), 2) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            WHERE a.is_internal = FALSE AND t.is_reversal = FALSE
              AND t.transaction_id NOT IN (
                  SELECT reversal_of_transaction_id FROM fact_transaction WHERE reversal_of_transaction_id IS NOT NULL
              )
              AND date_part('year', t.transaction_date) = 2025 AND date_part('quarter', t.transaction_date) = 3
        """,
        "business_definition": "Customer-activity volume reporting uses transaction_date, net of reversals and internal accounts.",
    },
    # Ambiguity 3: open vs active
    {
        "id": "dev-07",
        "ambiguity_tag": "open_vs_active_account",
        "question": "How many active customers do we have in the Eastern-ON region?",
        "sql": "SELECT COUNT(*) FROM dim_customer WHERE is_active = TRUE AND region = 'Eastern-ON'",
        "business_definition": "'Active' means behavioral recency, scoped to a region.",
    },
    {
        "id": "dev-08",
        "ambiguity_tag": "open_vs_active_account",
        "question": "How many customers have at least one open account in the GTA-Central region?",
        "sql": """
            SELECT COUNT(DISTINCT c.customer_id) FROM dim_customer c
            JOIN dim_account a ON a.customer_id = c.customer_id
            WHERE a.status = 'open' AND c.region = 'GTA-Central'
        """,
        "business_definition": "Structural (open-account) reading, scoped to a region.",
    },
    {
        "id": "dev-09",
        "ambiguity_tag": "open_vs_active_account",
        "question": "How many active customers do we have in the GTA-Central region?",
        "sql": "SELECT COUNT(*) FROM dim_customer WHERE is_active = TRUE AND region = 'GTA-Central'",
        "business_definition": "Behavioral reading of the same region as dev-08, for direct contrast.",
    },
    # Ambiguity 4: month-end vs avg daily balance
    {
        "id": "dev-10",
        "ambiguity_tag": "month_end_vs_avg_daily_balance",
        "question": "What was the average daily deposit balance in Q1 2026?",
        "sql": "SELECT ROUND(AVG(balance_amount), 2) FROM fact_daily_balance WHERE balance_date BETWEEN '2026-01-01' AND '2026-03-31'",
        "business_definition": "Average daily balance is the mean across every day in the period.",
    },
    {
        "id": "dev-11",
        "ambiguity_tag": "month_end_vs_avg_daily_balance",
        "question": "What was total deposit balance across all accounts as of March 31, 2026?",
        "sql": "SELECT ROUND(SUM(balance_amount), 2) FROM fact_daily_balance WHERE balance_date = '2026-03-31'",
        "business_definition": "Month-end balance is a snapshot on the last calendar day.",
    },
    {
        "id": "dev-12",
        "ambiguity_tag": "month_end_vs_avg_daily_balance",
        "question": "What was the average daily balance in April 2026 for deposit accounts?",
        "sql": "SELECT ROUND(AVG(balance_amount), 2) FROM fact_daily_balance WHERE balance_date BETWEEN '2026-04-01' AND '2026-04-30'",
        "business_definition": "Average daily balance is the mean across every day in the period.",
    },
    # Ambiguity 5: written-off loans
    {
        "id": "dev-13",
        "ambiguity_tag": "written_off_loans",
        "question": "What is our delinquency rate (30+ days past due) for the active loan portfolio as of March 2026?",
        "sql": """
            WITH latest AS (
                SELECT loan_account_id, days_past_due,
                       ROW_NUMBER() OVER (PARTITION BY loan_account_id ORDER BY payment_date DESC) AS rn
                FROM fact_loan_payment WHERE payment_date <= '2026-03-31'
            )
            SELECT ROUND(100.0 * SUM(CASE WHEN l.days_past_due >= 30 THEN 1 ELSE 0 END) / COUNT(*), 2)
            FROM latest l JOIN dim_account a ON l.loan_account_id = a.account_id
            WHERE l.rn = 1 AND a.write_off_flag = FALSE
        """,
        "business_definition": "Delinquency rate excludes written-off loans from the active book.",
    },
    {
        "id": "dev-14",
        "ambiguity_tag": "written_off_loans",
        "question": "How many loans in our active portfolio are 60+ days past due, as of March 2026?",
        "sql": """
            WITH latest AS (
                SELECT loan_account_id, days_past_due,
                       ROW_NUMBER() OVER (PARTITION BY loan_account_id ORDER BY payment_date DESC) AS rn
                FROM fact_loan_payment WHERE payment_date <= '2026-03-31'
            )
            SELECT COUNT(*) FROM latest l JOIN dim_account a ON l.loan_account_id = a.account_id
            WHERE l.rn = 1 AND a.write_off_flag = FALSE AND l.days_past_due >= 60
        """,
        "business_definition": "Active-portfolio delinquency count excludes written-off loans.",
    },
    {
        "id": "dev-15",
        "ambiguity_tag": "written_off_loans",
        "question": "How many loans have been written off, as of June 2026?",
        "sql": """
            SELECT COUNT(*) FROM dim_account a
            JOIN dim_product p ON a.product_id = p.product_id
            WHERE p.product_type = 'loan' AND a.write_off_flag = TRUE
        """,
        "business_definition": "Charge-off count is a distinct metric from delinquency rate -- written-off loans get their own metric rather than distorting the active-book rate.",
    },
    # Ambiguity 6: reversed transactions
    {
        "id": "dev-16",
        "ambiguity_tag": "reversed_transactions",
        "question": "What was total transaction volume (dollar amount) in 2024, net of reversals?",
        "sql": """
            SELECT ROUND(SUM(ABS(t.amount)), 2) FROM fact_transaction t
            WHERE date_part('year', t.transaction_date) = 2024 AND t.is_reversal = FALSE
              AND t.transaction_id NOT IN (
                  SELECT reversal_of_transaction_id FROM fact_transaction WHERE reversal_of_transaction_id IS NOT NULL
              )
        """,
        "business_definition": "Volume nets reversal pairs out to zero net activity.",
    },
    {
        "id": "dev-17",
        "ambiguity_tag": "reversed_transactions",
        "question": "How many transactions from 2024 were later reversed?",
        "sql": """
            SELECT COUNT(DISTINCT r.reversal_of_transaction_id) FROM fact_transaction r
            JOIN fact_transaction o ON r.reversal_of_transaction_id = o.transaction_id
            WHERE date_part('year', o.transaction_date) = 2024
        """,
        "business_definition": "Counts distinct original transactions later reversed.",
    },
    {
        "id": "dev-18",
        "ambiguity_tag": "reversed_transactions",
        "question": "What was total transaction volume in 2025 if reversals are not netted out?",
        "sql": """
            SELECT ROUND(SUM(ABS(amount)), 2) FROM fact_transaction
            WHERE date_part('year', transaction_date) = 2025
        """,
        "business_definition": "Explicit request for the naive, un-netted figure -- a well-defined but non-standard reading, used to test that the model follows explicit intent rather than always applying the governed default.",
    },
    # Ambiguity 7: internal accounts
    {
        "id": "dev-19",
        "ambiguity_tag": "internal_accounts",
        "question": "What was total customer transaction volume in 2024?",
        "sql": """
            SELECT ROUND(SUM(ABS(t.amount)), 2) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            WHERE a.is_internal = FALSE AND t.is_reversal = FALSE
              AND t.transaction_id NOT IN (
                  SELECT reversal_of_transaction_id FROM fact_transaction WHERE reversal_of_transaction_id IS NOT NULL
              )
              AND date_part('year', t.transaction_date) = 2024
        """,
        "business_definition": "Customer transaction volume excludes internal/GL accounts.",
    },
    {
        "id": "dev-20",
        "ambiguity_tag": "internal_accounts",
        "question": "How many transactions did customers make in 2024?",
        "sql": """
            SELECT COUNT(*) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            WHERE a.is_internal = FALSE AND date_part('year', t.transaction_date) = 2024
        """,
        "business_definition": "Customer transaction count excludes internal/GL account activity.",
    },
    {
        "id": "dev-21",
        "ambiguity_tag": "internal_accounts",
        "question": "How many transactions were recorded across all accounts, including internal ones, in 2025?",
        "sql": """
            SELECT COUNT(*) FROM fact_transaction
            WHERE date_part('year', transaction_date) = 2025
        """,
        "business_definition": "Explicit request to include internal accounts -- tests that the model follows stated intent rather than always excluding them by default.",
    },
    # Ambiguity 8: customer vs branch location
    {
        "id": "dev-22",
        "ambiguity_tag": "customer_vs_branch_location",
        "question": "What was total transaction volume attributed to the Mississauga West branch in 2025, based on customers' home branch?",
        "sql": """
            SELECT ROUND(SUM(ABS(t.amount)), 2) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            JOIN dim_branch b ON a.home_branch_id = b.branch_id
            WHERE b.branch_name = 'Mississauga West' AND a.is_internal = FALSE AND t.is_reversal = FALSE
              AND t.transaction_id NOT IN (
                  SELECT reversal_of_transaction_id FROM fact_transaction WHERE reversal_of_transaction_id IS NOT NULL
              )
              AND date_part('year', t.transaction_date) = 2025
        """,
        "business_definition": "Branch performance reporting attributes volume to the customer's home branch.",
    },
    {
        "id": "dev-23",
        "ambiguity_tag": "customer_vs_branch_location",
        "question": "How many transactions physically occurred at the Kanata branch in 2025, regardless of the customer's home branch?",
        "sql": """
            SELECT COUNT(*) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            JOIN dim_branch b ON t.branch_id = b.branch_id
            WHERE b.branch_name = 'Kanata' AND a.is_internal = FALSE
              AND date_part('year', t.transaction_date) = 2025
        """,
        "business_definition": "Foot-traffic reporting attributes activity to the transaction's physical branch.",
    },
    {
        "id": "dev-24",
        "ambiguity_tag": "customer_vs_branch_location",
        "question": "What was total transaction volume attributed to the Brampton North branch in 2025, based on customers' home branch?",
        "sql": """
            SELECT ROUND(SUM(ABS(t.amount)), 2) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            JOIN dim_branch b ON a.home_branch_id = b.branch_id
            WHERE b.branch_name = 'Brampton North' AND a.is_internal = FALSE AND t.is_reversal = FALSE
              AND t.transaction_id NOT IN (
                  SELECT reversal_of_transaction_id FROM fact_transaction WHERE reversal_of_transaction_id IS NOT NULL
              )
              AND date_part('year', t.transaction_date) = 2025
        """,
        "business_definition": "Branch performance reporting attributes volume to the customer's home branch.",
    },
]

# --- 4 dev out-of-scope questions: unanswerable, distinct from the sealed 8 --

OUT_OF_SCOPE_QUESTIONS = [
    {
        "id": "oos-dev-01",
        "question": "Which customers are likely to churn next quarter?",
        "business_definition": "Requires a predictive/propensity model; no such model exists in the warehouse.",
    },
    {
        "id": "oos-dev-02",
        "question": "Show me revenue by sales representative.",
        "business_definition": "No sales-representative dimension exists in the schema.",
    },
    {
        "id": "oos-dev-03",
        "question": "What is the current prime interest rate?",
        "business_definition": "External macroeconomic data, entirely out of domain for a transactional warehouse.",
    },
    {
        "id": "oos-dev-04",
        "question": "How many mobile app logins did we have last month?",
        "business_definition": "No digital-channel/engagement data exists in the schema.",
    },
]


def run_in_scope(con: duckdb.DuckDBPyConnection) -> list:
    results = []
    for q in IN_SCOPE_QUESTIONS:
        value = con.execute(q["sql"]).fetchone()[0]
        if value is not None:
            value = float(value)
        results.append({
            "id": q["id"],
            "question": q["question"],
            "answerable": True,
            "ambiguity_tag": q["ambiguity_tag"],
            "sql": q["sql"].strip(),
            "expected_result": value,
            "business_definition": q["business_definition"],
        })
    return results


def build_out_of_scope() -> list:
    results = []
    for q in OUT_OF_SCOPE_QUESTIONS:
        results.append({
            "id": q["id"],
            "question": q["question"],
            "answerable": False,
            "ambiguity_tag": None,
            "sql": None,
            "expected_result": None,
            "business_definition": q["business_definition"],
        })
    return results


def main() -> None:
    con = duckdb.connect(WAREHOUSE, read_only=True)
    in_scope = run_in_scope(con)
    con.close()

    with open(OUT_DEV, "w") as f:
        yaml.safe_dump(in_scope, f, sort_keys=False, allow_unicode=True)

    with open(OUT_DEV_OOS, "w") as f:
        yaml.safe_dump(build_out_of_scope(), f, sort_keys=False, allow_unicode=True)

    print(f"Wrote {len(in_scope)} dev in-scope questions to {OUT_DEV}")
    print(f"Wrote {len(OUT_OF_SCOPE_QUESTIONS)} dev out-of-scope questions to {OUT_DEV_OOS}")


if __name__ == "__main__":
    main()
