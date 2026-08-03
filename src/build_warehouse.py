"""Weeks 3-5 build: a synthetic banking warehouse with all 8 ambiguities live.

Deterministic (seeded) so a clean rebuild reproduces identical data, which is
required for the eval questions in evals/ to have stable expected results.

Usage:
    python src/build_warehouse.py [output_path]
"""

import random
import sys
from datetime import date, timedelta

import duckdb

SEED = 42
AS_OF_DATE = date(2026, 6, 30)  # end of the last full quarter
DATE_START = date(2024, 1, 1)
DATE_END = date(2026, 6, 30)
DORMANCY_CUTOFF = date(2025, 12, 31)  # dormant customers have no activity after this
DORMANT_SHARE = 0.2

DEFAULT_OUTPUT = "warehouse.duckdb"


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def build_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DROP TABLE IF EXISTS fact_loan_payment")
    con.execute("DROP TABLE IF EXISTS fact_daily_balance")
    con.execute("DROP TABLE IF EXISTS fact_transaction")
    con.execute("DROP TABLE IF EXISTS dim_account")
    con.execute("DROP TABLE IF EXISTS dim_customer")
    con.execute("DROP TABLE IF EXISTS dim_product")
    con.execute("DROP TABLE IF EXISTS dim_branch")
    con.execute("DROP TABLE IF EXISTS dim_date")

    con.execute("""
        CREATE TABLE dim_date (
            date_key DATE PRIMARY KEY,
            year INTEGER,
            quarter INTEGER,
            month INTEGER,
            day INTEGER,
            is_quarter_end BOOLEAN,
            is_month_end BOOLEAN
        )
    """)
    con.execute("""
        CREATE TABLE dim_branch (
            branch_id INTEGER PRIMARY KEY,
            branch_name VARCHAR,
            city VARCHAR,
            region VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE dim_product (
            product_id INTEGER PRIMARY KEY,
            product_name VARCHAR,
            product_type VARCHAR  -- deposit | loan | credit | internal
        )
    """)
    con.execute("""
        CREATE TABLE dim_customer (
            customer_id INTEGER PRIMARY KEY,
            customer_name VARCHAR,
            home_branch_id INTEGER,
            region VARCHAR,
            is_active BOOLEAN,
            signup_date DATE
        )
    """)
    con.execute("""
        CREATE TABLE dim_account (
            account_id INTEGER PRIMARY KEY,
            customer_id INTEGER,  -- NULL for internal accounts
            product_id INTEGER,
            home_branch_id INTEGER,
            open_date DATE,
            close_date DATE,
            status VARCHAR,        -- open | closed
            is_internal BOOLEAN,
            write_off_flag BOOLEAN,
            write_off_date DATE
        )
    """)
    con.execute("""
        CREATE TABLE fact_transaction (
            transaction_id INTEGER PRIMARY KEY,
            account_id INTEGER,
            transaction_date DATE,
            posting_date DATE,
            branch_id INTEGER,      -- branch where the transaction occurred
            transaction_type VARCHAR,  -- fee | deposit | withdrawal | purchase
            amount DECIMAL(12,2),
            fee_waived BOOLEAN,
            is_reversal BOOLEAN,
            reversal_of_transaction_id INTEGER
        )
    """)
    con.execute("""
        CREATE TABLE fact_daily_balance (
            account_id INTEGER,
            balance_date DATE,
            balance_amount DECIMAL(12,2)
        )
    """)
    con.execute("""
        CREATE TABLE fact_loan_payment (
            loan_account_id INTEGER,
            payment_date DATE,
            payment_amount DECIMAL(12,2),
            days_past_due INTEGER
        )
    """)
    con.execute("""
        CREATE TABLE fact_interest_monthly (
            account_id INTEGER,
            month_start DATE,
            interest_income DECIMAL(12,2),   -- loans only; 0 for deposit rows
            interest_expense DECIMAL(12,2),  -- deposits only; 0 for loan rows
            outstanding_loan_balance DECIMAL(12,2)  -- loans only; 0 for deposit rows
        )
    """)


def seed_dim_date(con: duckdb.DuckDBPyConnection) -> None:
    rows = []
    for d in daterange(DATE_START, DATE_END):
        quarter = (d.month - 1) // 3 + 1
        next_day = d + timedelta(days=1)
        is_month_end = next_day.month != d.month
        is_quarter_end = is_month_end and quarter != (next_day.month - 1) // 3 + 1
        rows.append((d, d.year, quarter, d.month, d.day, is_quarter_end, is_month_end))
    con.executemany("INSERT INTO dim_date VALUES (?, ?, ?, ?, ?, ?, ?)", rows)


BRANCHES = [
    (1, "Head Office", "Toronto", "GTA-Central"),
    (2, "King Street", "Toronto", "GTA-Central"),
    (3, "Mississauga West", "Mississauga", "GTA-West"),
    (4, "Brampton North", "Brampton", "GTA-West"),
    (5, "Ottawa Downtown", "Ottawa", "Eastern-ON"),
    (6, "Kanata", "Ottawa", "Eastern-ON"),
]

PRODUCTS = [
    (1, "Chequing", "deposit"),
    (2, "Savings", "deposit"),
    (3, "Personal Loan", "loan"),
    (4, "Mortgage", "loan"),
    (5, "Credit Card", "credit"),
    (6, "Internal GL", "internal"),
]


def seed_dim_branch(con: duckdb.DuckDBPyConnection) -> None:
    con.executemany("INSERT INTO dim_branch VALUES (?, ?, ?, ?)", BRANCHES)


def seed_dim_product(con: duckdb.DuckDBPyConnection) -> None:
    con.executemany("INSERT INTO dim_product VALUES (?, ?, ?)", PRODUCTS)


FIRST_NAMES = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
               "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
               "Thomas", "Sarah", "Charles", "Karen", "Umut", "Ayse", "Mehmet", "Fatma", "Ahmet"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
              "Rodriguez", "Martinez", "Wilson", "Anderson", "Taylor", "Thomas", "Moore", "Jackson",
              "Yilmaz", "Kaya", "Demir", "Sahin"]


def seed_dim_customer(con: duckdb.DuckDBPyConnection, rng: random.Random, n: int = 150) -> None:
    rows = []
    for cid in range(1, n + 1):
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        branch = rng.choice(BRANCHES)
        signup_offset = rng.randint(0, (DATE_END - DATE_START).days - 30)
        signup_date = DATE_START + timedelta(days=signup_offset)
        rows.append((cid, name, branch[0], branch[3], False, signup_date))
    con.executemany("INSERT INTO dim_customer VALUES (?, ?, ?, ?, ?, ?)", rows)


def seed_dim_account(con: duckdb.DuckDBPyConnection, rng: random.Random):
    customers = con.execute("SELECT customer_id, home_branch_id, signup_date FROM dim_customer").fetchall()
    rows = []
    account_id = 1

    # Internal / GL accounts: no customer, tied to Head Office
    for _ in range(10):
        rows.append((account_id, None, 6, 1, DATE_START, None, "open", True, False, None))
        account_id += 1

    # Deposit + credit accounts: most customers get 1-2
    for cid, home_branch, signup_date in customers:
        n_accounts = rng.choices([1, 2], weights=[0.6, 0.4])[0]
        products = rng.sample([1, 2, 5], k=min(n_accounts, 3))
        for pid in products:
            open_date = signup_date + timedelta(days=rng.randint(0, 30))
            status = "open" if rng.random() > 0.05 else "closed"
            close_date = None
            if status == "closed":
                close_date = open_date + timedelta(days=rng.randint(60, 500))
                close_date = min(close_date, DATE_END)
            rows.append((account_id, cid, pid, home_branch, open_date, close_date,
                         status, False, False, None))
            account_id += 1

    # Loan accounts: ~40, subset of customers
    loan_customers = rng.sample(customers, k=40)
    for cid, home_branch, signup_date in loan_customers:
        pid = rng.choice([3, 4])
        open_date = signup_date + timedelta(days=rng.randint(0, 60))
        write_off = rng.random() < 0.15
        write_off_date = None
        status = "open"
        if write_off:
            write_off_date = open_date + timedelta(days=rng.randint(180, 700))
            write_off_date = min(write_off_date, DATE_END)
            status = "closed"
        rows.append((account_id, cid, pid, home_branch, open_date, None,
                     status, False, write_off, write_off_date))
        account_id += 1

    con.executemany("INSERT INTO dim_account VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


TXN_TYPES = ["fee", "deposit", "withdrawal", "purchase"]
TXN_WEIGHTS = [0.15, 0.25, 0.25, 0.35]


def seed_fact_transaction(con: duckdb.DuckDBPyConnection, rng: random.Random, n: int = 6000):
    accounts = con.execute("""
        SELECT account_id, customer_id, home_branch_id, is_internal, open_date,
               COALESCE(close_date, DATE '2026-06-30') AS effective_close
        FROM dim_account
    """).fetchall()

    # Weight selection so ~5% of transactions land on internal accounts
    internal_accts = [a for a in accounts if a[3]]
    normal_accts = [a for a in accounts if not a[3]]

    # Deliberately dormant customers: accounts stay open, but no activity after
    # DORMANCY_CUTOFF, well clear of the trailing-90-day "active" window as of
    # AS_OF_DATE. Without this, random activity spread over 2.5 years makes
    # nearly every customer "active" by chance, and the open-vs-active
    # ambiguity has no real gap to detect.
    all_customer_ids = sorted({a[1] for a in normal_accts if a[1] is not None})
    dormant_customers = set(
        rng.sample(all_customer_ids, k=int(len(all_customer_ids) * DORMANT_SHARE))
    )
    dormancy_cutoff_offset = (DORMANCY_CUTOFF - DATE_START).days

    rows = []
    txn_id = 1
    reversible_pool = []  # (transaction_id, account_id, home_branch, txn_date, txn_type, amount)

    span_days = (DATE_END - DATE_START).days

    for _ in range(n):
        if rng.random() < 0.05 and internal_accts:
            acct = rng.choice(internal_accts)
        else:
            acct = rng.choice(normal_accts)
        account_id, customer_id, home_branch, is_internal, open_date, effective_close = acct

        lo = max(0, (open_date - DATE_START).days)
        hi = min(span_days, (effective_close - DATE_START).days)
        if customer_id in dormant_customers:
            hi = min(hi, dormancy_cutoff_offset)
        if hi <= lo:
            continue
        txn_date = DATE_START + timedelta(days=rng.randint(lo, hi))

        txn_type = rng.choices(TXN_TYPES, weights=TXN_WEIGHTS)[0]
        amount = round(rng.uniform(10, 2500), 2)
        if txn_type in ("withdrawal", "purchase"):
            amount = -amount
        fee_waived = False
        if txn_type == "fee":
            amount = -round(rng.uniform(5, 75), 2)
            fee_waived = rng.random() < 0.2

        # posting lag 0-3 days, occasionally crossing a quarter/month boundary
        posting_date = txn_date + timedelta(days=rng.randint(0, 3))

        # 15% of the time the transaction happens at a different branch than home
        branch_id = home_branch if rng.random() > 0.15 else rng.choice(BRANCHES)[0]

        rows.append((txn_id, account_id, txn_date, posting_date, branch_id,
                     txn_type, amount, fee_waived, False, None))

        if txn_type in ("deposit", "withdrawal", "purchase"):
            reversible_pool.append((txn_id, account_id, home_branch, txn_date, txn_type, amount))

        txn_id += 1

    # Reversals: ~3% of reversible transactions get reversed a few days later
    n_reversals = int(len(reversible_pool) * 0.03)
    for orig_txn_id, account_id, home_branch, orig_date, txn_type, amount in rng.sample(
        reversible_pool, k=min(n_reversals, len(reversible_pool))
    ):
        rev_date = orig_date + timedelta(days=rng.randint(1, 5))
        if rev_date > DATE_END:
            continue
        rev_posting = rev_date + timedelta(days=rng.randint(0, 3))
        branch_id = home_branch if rng.random() > 0.15 else rng.choice(BRANCHES)[0]
        rows.append((txn_id, account_id, rev_date, rev_posting, branch_id,
                     txn_type, -amount, False, True, orig_txn_id))
        txn_id += 1

    con.executemany(
        "INSERT INTO fact_transaction VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )


def seed_fact_daily_balance(con: duckdb.DuckDBPyConnection, rng: random.Random):
    deposit_accounts = con.execute("""
        SELECT a.account_id
        FROM dim_account a
        JOIN dim_product p ON a.product_id = p.product_id
        WHERE p.product_type = 'deposit' AND a.status = 'open' AND a.is_internal = FALSE
    """).fetchall()

    balance_start = date(2026, 1, 1)
    rows = []
    for (account_id,) in deposit_accounts:
        balance = round(rng.uniform(500, 15000), 2)
        for d in daterange(balance_start, DATE_END):
            # small daily random walk, occasional larger swings (payday-like deposits)
            delta = rng.uniform(-150, 150)
            if rng.random() < 0.05:
                delta += rng.choice([-1, 1]) * rng.uniform(500, 2000)
            balance = max(0, balance + delta)
            rows.append((account_id, d, round(balance, 2)))

    con.executemany("INSERT INTO fact_daily_balance VALUES (?, ?, ?)", rows)


def seed_fact_loan_payment(con: duckdb.DuckDBPyConnection, rng: random.Random):
    loans = con.execute("""
        SELECT account_id, open_date, write_off_flag, write_off_date
        FROM dim_account a
        JOIN dim_product p ON a.product_id = p.product_id
        WHERE p.product_type = 'loan'
    """).fetchall()

    rows = []
    for account_id, open_date, write_off_flag, write_off_date in loans:
        end = write_off_date if write_off_flag else AS_OF_DATE
        month = date(open_date.year, open_date.month, 1)
        months_remaining_to_writeoff = None
        if write_off_flag:
            total_months = max(1, (end.year - month.year) * 12 + (end.month - month.month))
            months_remaining_to_writeoff = total_months

        m_index = 0
        while month <= end:
            payment_amount = round(rng.uniform(200, 1800), 2)
            dpd = 0
            if write_off_flag and months_remaining_to_writeoff:
                months_to_end = (end.year - month.year) * 12 + (end.month - month.month)
                if months_to_end <= 4:
                    dpd = [120, 90, 60, 30][min(months_to_end, 3)]
            else:
                if rng.random() < 0.08:
                    dpd = rng.choice([30, 60])
            rows.append((account_id, month, payment_amount, dpd))
            # advance one month
            if month.month == 12:
                month = date(month.year + 1, 1, 1)
            else:
                month = date(month.year, month.month + 1, 1)
            m_index += 1

    con.executemany("INSERT INTO fact_loan_payment VALUES (?, ?, ?, ?)", rows)


# Simplified interest model for net_interest_income / net_interest_margin.
# Not a real amortization engine: deposit interest is a fixed monthly rate on
# the account's actual avg daily balance (only exists for the Jan-Jun 2026
# window fact_daily_balance covers); loan interest is a fixed monthly rate on
# a synthetic origination amount straight-line amortized to zero over a fixed
# term. Documented as a simplification, not a claim of realism.
DEPOSIT_MONTHLY_RATE = {"Chequing": 0.0002, "Savings": 0.0015}
LOAN_TERM_MONTHS = {"Personal Loan": 60, "Mortgage": 300}
LOAN_MONTHLY_RATE = {"Personal Loan": 0.007, "Mortgage": 0.0035}
LOAN_ORIGINATION_RANGE = {"Personal Loan": (5000, 40000), "Mortgage": (150000, 500000)}


def seed_fact_interest_monthly(con: duckdb.DuckDBPyConnection, rng: random.Random):
    rows = []

    deposit_rows = con.execute("""
        SELECT b.account_id, date_trunc('month', b.balance_date) AS month_start,
               AVG(b.balance_amount) AS avg_balance, p.product_name
        FROM fact_daily_balance b
        JOIN dim_account a ON b.account_id = a.account_id
        JOIN dim_product p ON a.product_id = p.product_id
        GROUP BY b.account_id, date_trunc('month', b.balance_date), p.product_name
    """).fetchall()
    for account_id, month_start, avg_balance, product_name in deposit_rows:
        rate = DEPOSIT_MONTHLY_RATE.get(product_name, 0.0)
        interest_expense = round(float(avg_balance) * rate, 2)
        rows.append((account_id, month_start, 0.0, interest_expense, 0.0))

    loans = con.execute("""
        SELECT a.account_id, a.open_date, a.write_off_flag, a.write_off_date, p.product_name
        FROM dim_account a
        JOIN dim_product p ON a.product_id = p.product_id
        WHERE p.product_type = 'loan'
    """).fetchall()
    for account_id, open_date, write_off_flag, write_off_date, product_name in loans:
        lo, hi = LOAN_ORIGINATION_RANGE[product_name]
        origination = rng.uniform(lo, hi)
        term = LOAN_TERM_MONTHS[product_name]
        rate = LOAN_MONTHLY_RATE[product_name]
        end = write_off_date if write_off_flag else AS_OF_DATE

        month = date(open_date.year, open_date.month, 1)
        month_index = 0
        while month <= end:
            fraction_remaining = max(0.0, 1 - month_index / term)
            outstanding = round(origination * fraction_remaining, 2)
            interest_income = round(outstanding * rate, 2)
            rows.append((account_id, month, interest_income, 0.0, outstanding))
            month_index += 1
            if month.month == 12:
                month = date(month.year + 1, 1, 1)
            else:
                month = date(month.year, month.month + 1, 1)

    con.executemany(
        "INSERT INTO fact_interest_monthly VALUES (?, ?, ?, ?, ?)", rows
    )


def update_customer_activity(con: duckdb.DuckDBPyConnection) -> None:
    cutoff = AS_OF_DATE - timedelta(days=90)
    con.execute("""
        UPDATE dim_customer
        SET is_active = EXISTS (
            SELECT 1
            FROM fact_transaction t
            JOIN dim_account a ON t.account_id = a.account_id
            WHERE a.customer_id = dim_customer.customer_id
              AND t.transaction_date >= ?
        )
    """, [cutoff])


def build_into(con: duckdb.DuckDBPyConnection) -> None:
    """Builds the warehouse schema and seed data into an already-open
    connection (file-backed or in-memory)."""
    rng = random.Random(SEED)

    build_schema(con)
    seed_dim_date(con)
    seed_dim_branch(con)
    seed_dim_product(con)
    seed_dim_customer(con, rng)
    seed_dim_account(con, rng)
    seed_fact_transaction(con, rng)
    seed_fact_daily_balance(con, rng)
    seed_fact_loan_payment(con, rng)
    seed_fact_interest_monthly(con, rng)
    update_customer_activity(con)


def build(output_path: str) -> None:
    con = duckdb.connect(output_path)
    build_into(con)

    con.close()


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUTPUT
    build(output)
    print(f"Built warehouse at {output}")
