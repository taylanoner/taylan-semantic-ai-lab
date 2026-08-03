select
    account_id,
    month_start,
    interest_income,
    interest_expense,
    outstanding_loan_balance
from {{ source('raw', 'fact_interest_monthly') }}
