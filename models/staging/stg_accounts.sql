select
    account_id,
    customer_id,
    product_id,
    home_branch_id,
    open_date,
    close_date,
    status,
    is_internal,
    write_off_flag,
    write_off_date
from {{ source('raw', 'dim_account') }}
