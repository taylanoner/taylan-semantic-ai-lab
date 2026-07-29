"""Week 7: warehouse build sanity tests.

Run with:
    pytest tests/test_warehouse.py -v
"""

def test_dim_branch_has_six_branches(warehouse):
    count = warehouse.execute("SELECT COUNT(*) FROM dim_branch").fetchone()[0]
    assert count == 6


def test_dim_customer_has_150_customers(warehouse):
    count = warehouse.execute("SELECT COUNT(*) FROM dim_customer").fetchone()[0]
    assert count == 150


def test_fact_transaction_is_nonempty(warehouse):
    count = warehouse.execute("SELECT COUNT(*) FROM fact_transaction").fetchone()[0]
    assert count > 5000


def test_gross_revenue_exceeds_net_revenue(warehouse):
    """Ambiguity #1 sanity check: gross fee revenue (all fees) must be
    strictly greater than net fee revenue (fees minus waived ones), otherwise
    the waived-fee seeding isn't doing anything."""
    gross = warehouse.execute("""
        SELECT -SUM(amount) FROM fact_transaction
        WHERE transaction_type = 'fee' AND is_reversal = FALSE
    """).fetchone()[0]
    net = warehouse.execute("""
        SELECT -SUM(amount) FROM fact_transaction
        WHERE transaction_type = 'fee' AND fee_waived = FALSE AND is_reversal = FALSE
    """).fetchone()[0]
    assert gross > net


def test_open_account_count_differs_from_active_customer_count(warehouse):
    """Ambiguity #3 sanity check: the two readings must produce different
    numbers, otherwise the dormancy seeding regressed."""
    open_count = warehouse.execute("""
        SELECT COUNT(DISTINCT c.customer_id) FROM dim_customer c
        JOIN dim_account a ON a.customer_id = c.customer_id
        WHERE a.status = 'open'
    """).fetchone()[0]
    active_count = warehouse.execute(
        "SELECT COUNT(*) FROM dim_customer WHERE is_active = TRUE"
    ).fetchone()[0]
    assert open_count != active_count
