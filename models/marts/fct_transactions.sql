select
    t.transaction_id,
    t.account_id,
    t.transaction_date,
    t.posting_date,
    t.transaction_type,
    t.amount,
    t.fee_waived,
    b.branch_id,
    b.branch_name,
    b.region
from {{ ref('stg_transactions') }} as t
join {{ ref('stg_branches') }} as b
    on t.branch_id = b.branch_id
