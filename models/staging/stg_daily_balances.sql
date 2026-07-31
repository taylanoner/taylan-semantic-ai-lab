select
    account_id,
    balance_date,
    balance_amount
from {{ source('raw', 'fact_daily_balance') }}
