-- Ambiguity #5: write_off_flag is exposed as a dimension so metrics can
-- explicitly filter to the active book, rather than silently mixing
-- written-off loans into delinquency-rate calculations.
select
    d.loan_account_id,
    d.month_start,
    d.days_past_due,
    a.customer_id,
    a.product_id,
    a.write_off_flag
from {{ ref('int_loan_delinquency_monthly') }} as d
join {{ ref('stg_accounts') }} as a
    on d.loan_account_id = a.account_id
