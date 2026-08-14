-- One row per loan per month: the latest days_past_due on record as of that
-- month (a loan can have multiple payment records; we want the most recent
-- status, not a sum or average of days-past-due across records).
with ranked as (
    select
        loan_account_id,
        cast(date_trunc('month', payment_date) as date) as month_start,
        days_past_due,
        row_number() over (
            partition by loan_account_id, date_trunc('month', payment_date)
            order by payment_date desc
        ) as rn
    from {{ ref('stg_loan_payments') }}
)
select
    loan_account_id,
    month_start,
    days_past_due
from ranked
where rn = 1
