select
    c.customer_id,
    c.customer_name,
    c.is_active,
    c.signup_date,
    b.branch_id as home_branch_id,
    b.branch_name as home_branch_name,
    b.region
from {{ ref('stg_customers') }} as c
join {{ ref('stg_branches') }} as b
    on c.home_branch_id = b.branch_id
