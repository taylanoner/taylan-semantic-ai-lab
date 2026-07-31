select
    customer_id,
    customer_name,
    home_branch_id,
    region,
    is_active,
    signup_date
from {{ source('raw', 'dim_customer') }}
