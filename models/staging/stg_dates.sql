select
    date_key,
    year,
    quarter,
    month,
    day,
    is_quarter_end,
    is_month_end
from {{ source('raw', 'dim_date') }}
