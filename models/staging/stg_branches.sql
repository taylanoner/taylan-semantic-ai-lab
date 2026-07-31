select
    branch_id,
    branch_name,
    city,
    region
from {{ source('raw', 'dim_branch') }}
