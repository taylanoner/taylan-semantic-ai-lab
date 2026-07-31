select
    loan_account_id,
    payment_date,
    payment_amount,
    days_past_due
from {{ source('raw', 'fact_loan_payment') }}
