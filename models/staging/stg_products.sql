select
    product_id,
    product_name,
    product_type
from {{ source('raw', 'dim_product') }}
