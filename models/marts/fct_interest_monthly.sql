select
    i.account_id,
    i.month_start,
    i.interest_income,
    i.interest_expense,
    i.outstanding_loan_balance,
    a.customer_id,
    a.product_id
from {{ ref('stg_interest') }} as i
join {{ ref('stg_accounts') }} as a
    on i.account_id = a.account_id
