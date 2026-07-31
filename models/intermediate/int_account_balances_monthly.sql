-- Ambiguity #4: month-end and average-daily balance are two distinct, valid
-- measures. Exposing both as separately named columns removes the ambiguity
-- rather than picking one silently.
select
    account_id,
    date_trunc('month', balance_date) as month_start,
    avg(balance_amount) as avg_daily_balance,
    max(case when balance_date = last_day(balance_date) then balance_amount end) as month_end_balance
from {{ ref('stg_daily_balances') }}
group by account_id, date_trunc('month', balance_date)
