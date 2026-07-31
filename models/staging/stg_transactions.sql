select
    t.transaction_id,
    t.account_id,
    t.transaction_date,
    t.posting_date,
    t.branch_id,
    t.transaction_type,
    t.amount,
    t.fee_waived
from {{ source('raw', 'fact_transaction') }} as t
join {{ source('raw', 'dim_account') }} as a
    on t.account_id = a.account_id
where
    a.is_internal = false
    and t.is_reversal = false
    and t.transaction_id not in (
        select reversal_of_transaction_id
        from {{ source('raw', 'fact_transaction') }}
        where reversal_of_transaction_id is not null
    )