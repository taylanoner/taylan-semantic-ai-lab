-- Ambiguity #8: transaction-location branch and the customer's home branch
-- are two distinct, unambiguously named dimensions -- neither silently
-- stands in for the other. Governed branch-performance metrics should
-- default to home_branch_name; transaction_branch_name is for
-- foot-traffic/operational analysis.
select
    t.transaction_id,
    t.account_id,
    a.customer_id,
    a.product_id,
    t.transaction_date,
    t.posting_date,
    t.transaction_type,
    t.amount,
    t.fee_waived,
    txn_branch.branch_id as transaction_branch_id,
    txn_branch.branch_name as transaction_branch_name,
    txn_branch.region as transaction_region,
    home_branch.branch_id as home_branch_id,
    home_branch.branch_name as home_branch_name,
    home_branch.region as home_region
from {{ ref('stg_transactions') }} as t
join {{ ref('stg_accounts') }} as a
    on t.account_id = a.account_id
join {{ ref('stg_branches') }} as txn_branch
    on t.branch_id = txn_branch.branch_id
join {{ ref('stg_branches') }} as home_branch
    on a.home_branch_id = home_branch.branch_id
