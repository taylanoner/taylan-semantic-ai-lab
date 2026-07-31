select
    bal.account_id,
    a.customer_id,
    a.product_id,
    bal.month_start,
    bal.avg_daily_balance,
    bal.month_end_balance
from {{ ref('int_account_balances_monthly') }} as bal
join {{ ref('stg_accounts') }} as a
    on bal.account_id = a.account_id
