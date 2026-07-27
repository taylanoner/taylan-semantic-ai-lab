"""One-time generator for the SEALED held-out eval sets (evals/holdout.yaml,
evals/out_of_scope.yaml).

Per the plan: these 28 questions are written now, while still naive about the
semantic layer, then sealed. Run this ONCE to produce the YAML files, commit,
and do not run it again until week 16 -- rerunning it "quietly loads" the
sealed questions, which defeats the point of sealing even if no human reads
the output.

Usage:
    python scripts/generate_holdout_questions.py
"""

import yaml
import duckdb

WAREHOUSE = "warehouse.duckdb"
OUT_HOLDOUT = "evals/holdout.yaml"
OUT_OOS = "evals/out_of_scope.yaml"

# --- 20 held-out in-scope questions, ~2-3 per ambiguity -------------------

IN_SCOPE_QUESTIONS = [
    # Ambiguity 1: gross vs net revenue
    {
        "id": "holdout-01",
        "ambiguity_tag": "gross_vs_net_revenue",
        "question": "What was our total net fee revenue in 2024?",
        "sql": """
            SELECT ROUND(-SUM(amount), 2) FROM fact_transaction
            WHERE transaction_type = 'fee' AND fee_waived = FALSE AND is_reversal = FALSE
              AND date_part('year', transaction_date) = 2024
        """,
        "business_definition": "Net fee revenue excludes waived fees; 'revenue' without qualification defaults to net, not the naive sum of all fees charged.",
    },
    {
        "id": "holdout-02",
        "ambiguity_tag": "gross_vs_net_revenue",
        "question": "What was our total net fee revenue in 2025?",
        "sql": """
            SELECT ROUND(-SUM(amount), 2) FROM fact_transaction
            WHERE transaction_type = 'fee' AND fee_waived = FALSE AND is_reversal = FALSE
              AND date_part('year', transaction_date) = 2025
        """,
        "business_definition": "Net fee revenue excludes waived fees.",
    },
    {
        "id": "holdout-03",
        "ambiguity_tag": "gross_vs_net_revenue",
        "question": "What was total net fee revenue collected from Credit Card accounts in 2025?",
        "sql": """
            SELECT ROUND(-SUM(t.amount), 2) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            JOIN dim_product p ON a.product_id = p.product_id
            WHERE p.product_name = 'Credit Card' AND t.transaction_type = 'fee'
              AND t.fee_waived = FALSE AND t.is_reversal = FALSE
              AND date_part('year', t.transaction_date) = 2025
        """,
        "business_definition": "Net fee revenue excludes waived fees, scoped to a single product.",
    },
    # Ambiguity 2: posting vs transaction date
    {
        "id": "holdout-04",
        "ambiguity_tag": "posting_vs_transaction_date",
        "question": "How many transactions posted to the ledger in Q4 2025?",
        "sql": """
            SELECT COUNT(*) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            WHERE a.is_internal = FALSE
              AND date_part('year', t.posting_date) = 2025 AND date_part('quarter', t.posting_date) = 4
        """,
        "business_definition": "Ledger/period-close reporting uses posting_date, the date it hit the books.",
    },
    {
        "id": "holdout-05",
        "ambiguity_tag": "posting_vs_transaction_date",
        "question": "How many transactions did customers initiate in Q4 2025?",
        "sql": """
            SELECT COUNT(*) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            WHERE a.is_internal = FALSE
              AND date_part('year', t.transaction_date) = 2025 AND date_part('quarter', t.transaction_date) = 4
        """,
        "business_definition": "Customer-activity reporting uses transaction_date, when the customer acted, not when it settled.",
    },
    {
        "id": "holdout-06",
        "ambiguity_tag": "posting_vs_transaction_date",
        "question": "What was total transaction volume in Q2 2026, based on posting date?",
        "sql": """
            SELECT ROUND(SUM(ABS(t.amount)), 2) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            WHERE a.is_internal = FALSE AND t.is_reversal = FALSE
              AND t.transaction_id NOT IN (
                  SELECT reversal_of_transaction_id FROM fact_transaction WHERE reversal_of_transaction_id IS NOT NULL
              )
              AND date_part('year', t.posting_date) = 2026 AND date_part('quarter', t.posting_date) = 2
        """,
        "business_definition": "Period-close volume reporting uses posting_date; volume is also net of reversals and internal accounts as standard metric hygiene.",
    },
    # Ambiguity 3: open vs active
    {
        "id": "holdout-07",
        "ambiguity_tag": "open_vs_active_account",
        "question": "How many active customers do we have as of June 30, 2026?",
        "sql": "SELECT COUNT(*) FROM dim_customer WHERE is_active = TRUE",
        "business_definition": "'Active' means behavioral recency (a transaction in the trailing 90 days), not merely holding a non-closed account.",
    },
    {
        "id": "holdout-08",
        "ambiguity_tag": "open_vs_active_account",
        "question": "How many customers have at least one open account?",
        "sql": """
            SELECT COUNT(DISTINCT c.customer_id) FROM dim_customer c
            JOIN dim_account a ON a.customer_id = c.customer_id
            WHERE a.status = 'open'
        """,
        "business_definition": "This is deliberately the structural (open-account) reading, contrasted with holdout-07's behavioral reading of the same population.",
    },
    {
        "id": "holdout-09",
        "ambiguity_tag": "open_vs_active_account",
        "question": "How many active customers do we have in the GTA-West region?",
        "sql": "SELECT COUNT(*) FROM dim_customer WHERE is_active = TRUE AND region = 'GTA-West'",
        "business_definition": "'Active' means behavioral recency, scoped to a region.",
    },
    # Ambiguity 4: month-end vs avg daily balance
    {
        "id": "holdout-10",
        "ambiguity_tag": "month_end_vs_avg_daily_balance",
        "question": "What was the average daily deposit account balance in June 2026?",
        "sql": "SELECT ROUND(AVG(balance_amount), 2) FROM fact_daily_balance WHERE balance_date BETWEEN '2026-06-01' AND '2026-06-30'",
        "business_definition": "Average daily balance is the mean of every day's balance across the period, distinct from a single point-in-time snapshot.",
    },
    {
        "id": "holdout-11",
        "ambiguity_tag": "month_end_vs_avg_daily_balance",
        "question": "What was the total deposit balance across all accounts as of June 30, 2026?",
        "sql": "SELECT ROUND(SUM(balance_amount), 2) FROM fact_daily_balance WHERE balance_date = '2026-06-30'",
        "business_definition": "Month-end balance is a snapshot on the last calendar day, deliberately contrasted with holdout-10's average over the same month.",
    },
    {
        "id": "holdout-12",
        "ambiguity_tag": "month_end_vs_avg_daily_balance",
        "question": "What was the average daily balance in May 2026 for deposit accounts?",
        "sql": "SELECT ROUND(AVG(balance_amount), 2) FROM fact_daily_balance WHERE balance_date BETWEEN '2026-05-01' AND '2026-05-31'",
        "business_definition": "Average daily balance is the mean across every day in the period.",
    },
    # Ambiguity 5: written-off loans
    {
        "id": "holdout-13",
        "ambiguity_tag": "written_off_loans",
        "question": "What is our delinquency rate (30+ days past due) for the active loan portfolio as of June 2026?",
        "sql": """
            WITH latest AS (
                SELECT loan_account_id, days_past_due,
                       ROW_NUMBER() OVER (PARTITION BY loan_account_id ORDER BY payment_date DESC) AS rn
                FROM fact_loan_payment WHERE payment_date <= '2026-06-30'
            )
            SELECT ROUND(100.0 * SUM(CASE WHEN l.days_past_due >= 30 THEN 1 ELSE 0 END) / COUNT(*), 2)
            FROM latest l JOIN dim_account a ON l.loan_account_id = a.account_id
            WHERE l.rn = 1 AND a.write_off_flag = FALSE
        """,
        "business_definition": "Delinquency rate is scoped to the active loan book; written-off loans have moved to a separate charge-off process and are excluded from both numerator and denominator.",
    },
    {
        "id": "holdout-14",
        "ambiguity_tag": "written_off_loans",
        "question": "How many loans in our active portfolio are 60+ days past due, as of June 2026?",
        "sql": """
            WITH latest AS (
                SELECT loan_account_id, days_past_due,
                       ROW_NUMBER() OVER (PARTITION BY loan_account_id ORDER BY payment_date DESC) AS rn
                FROM fact_loan_payment WHERE payment_date <= '2026-06-30'
            )
            SELECT COUNT(*) FROM latest l JOIN dim_account a ON l.loan_account_id = a.account_id
            WHERE l.rn = 1 AND a.write_off_flag = FALSE AND l.days_past_due >= 60
        """,
        "business_definition": "Active-portfolio delinquency count excludes written-off loans.",
    },
    # Ambiguity 6: reversed transactions
    {
        "id": "holdout-15",
        "ambiguity_tag": "reversed_transactions",
        "question": "What was total transaction volume (dollar amount) in 2025, net of reversals?",
        "sql": """
            SELECT ROUND(SUM(ABS(t.amount)), 2) FROM fact_transaction t
            WHERE date_part('year', t.transaction_date) = 2025 AND t.is_reversal = FALSE
              AND t.transaction_id NOT IN (
                  SELECT reversal_of_transaction_id FROM fact_transaction WHERE reversal_of_transaction_id IS NOT NULL
              )
        """,
        "business_definition": "A reversed transaction represents zero net economic activity; the pair is netted out rather than counted twice.",
    },
    {
        "id": "holdout-16",
        "ambiguity_tag": "reversed_transactions",
        "question": "How many transactions from 2025 were later reversed?",
        "sql": """
            SELECT COUNT(DISTINCT r.reversal_of_transaction_id) FROM fact_transaction r
            JOIN fact_transaction o ON r.reversal_of_transaction_id = o.transaction_id
            WHERE date_part('year', o.transaction_date) = 2025
        """,
        "business_definition": "Counts distinct original transactions that were later reversed, regardless of when the reversal itself posted.",
    },
    # Ambiguity 7: internal accounts
    {
        "id": "holdout-17",
        "ambiguity_tag": "internal_accounts",
        "question": "What was total customer transaction volume in 2025?",
        "sql": """
            SELECT ROUND(SUM(ABS(t.amount)), 2) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            WHERE a.is_internal = FALSE AND t.is_reversal = FALSE
              AND t.transaction_id NOT IN (
                  SELECT reversal_of_transaction_id FROM fact_transaction WHERE reversal_of_transaction_id IS NOT NULL
              )
              AND date_part('year', t.transaction_date) = 2025
        """,
        "business_definition": "'Customer' transaction volume excludes the bank's own internal/GL accounts, which aren't customer activity.",
    },
    {
        "id": "holdout-18",
        "ambiguity_tag": "internal_accounts",
        "question": "How many transactions did customers make in 2025?",
        "sql": """
            SELECT COUNT(*) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            WHERE a.is_internal = FALSE AND date_part('year', t.transaction_date) = 2025
        """,
        "business_definition": "Customer transaction count excludes internal/GL account activity.",
    },
    # Ambiguity 8: customer vs branch location
    {
        "id": "holdout-19",
        "ambiguity_tag": "customer_vs_branch_location",
        "question": "What was total transaction volume attributed to the Ottawa Downtown branch in 2025, based on customers' home branch?",
        "sql": """
            SELECT ROUND(SUM(ABS(t.amount)), 2) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            JOIN dim_branch b ON a.home_branch_id = b.branch_id
            WHERE b.branch_name = 'Ottawa Downtown' AND a.is_internal = FALSE AND t.is_reversal = FALSE
              AND t.transaction_id NOT IN (
                  SELECT reversal_of_transaction_id FROM fact_transaction WHERE reversal_of_transaction_id IS NOT NULL
              )
              AND date_part('year', t.transaction_date) = 2025
        """,
        "business_definition": "Branch performance reporting attributes volume to the customer's home/registered branch, reflecting the relationship, not where a transaction physically happened.",
    },
    {
        "id": "holdout-20",
        "ambiguity_tag": "customer_vs_branch_location",
        "question": "How many transactions physically occurred at the King Street branch in 2025, regardless of the customer's home branch?",
        "sql": """
            SELECT COUNT(*) FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            JOIN dim_branch b ON t.branch_id = b.branch_id
            WHERE b.branch_name = 'King Street' AND a.is_internal = FALSE
              AND date_part('year', t.transaction_date) = 2025
        """,
        "business_definition": "Foot-traffic / operational-load reporting attributes activity to the branch where the transaction actually occurred, deliberately contrasted with holdout-19's home-branch attribution.",
    },
]

# --- 8 held-out out-of-scope questions: no valid answer exists -----------

OUT_OF_SCOPE_QUESTIONS = [
    {
        "id": "oos-holdout-01",
        "question": "What is our current regulatory capital adequacy ratio (CAR)?",
        "business_definition": "Regulatory capital data is not modeled in this warehouse at all; no valid query exists.",
    },
    {
        "id": "oos-holdout-02",
        "question": "Which customers are likely to default on their loan in the next 6 months?",
        "business_definition": "Requires a predictive/risk model; no such model or scored output exists in the warehouse.",
    },
    {
        "id": "oos-holdout-03",
        "question": "What is the total number of transactions processed by each teller today?",
        "business_definition": "No teller/employee dimension exists in the schema.",
    },
    {
        "id": "oos-holdout-04",
        "question": "How does our net interest margin compare to Scotiabank's this quarter?",
        "business_definition": "Competitor financial data is out of domain entirely; not something this warehouse could ever contain.",
    },
    {
        "id": "oos-holdout-05",
        "question": "What is the projected loan default rate for next year under a recession scenario?",
        "business_definition": "Requires forecasting/scenario modeling; the warehouse holds historical facts, not projections.",
    },
    {
        "id": "oos-holdout-06",
        "question": "Show me total transaction volume by customer's marital status.",
        "business_definition": "No marital-status attribute exists on dim_customer; the dimension doesn't exist.",
    },
    {
        "id": "oos-holdout-07",
        "question": "What was total headcount cost for the Ottawa Downtown branch last year?",
        "business_definition": "HR/payroll cost data is out of domain entirely; not modeled anywhere in this warehouse.",
    },
    {
        "id": "oos-holdout-08",
        "question": "What is the average customer satisfaction score by branch?",
        "business_definition": "No survey/satisfaction data exists in the schema.",
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

    with open(OUT_HOLDOUT, "w") as f:
        yaml.safe_dump(in_scope, f, sort_keys=False, allow_unicode=True)

    with open(OUT_OOS, "w") as f:
        yaml.safe_dump(build_out_of_scope(), f, sort_keys=False, allow_unicode=True)

    print(f"Wrote {len(in_scope)} held-out in-scope questions to {OUT_HOLDOUT}")
    print(f"Wrote {len(OUT_OF_SCOPE_QUESTIONS)} held-out out-of-scope questions to {OUT_OOS}")


if __name__ == "__main__":
    main()
