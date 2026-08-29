-- Singular test: ensure no order date exists beyond current date
select *
from {{ ref('stg_orders') }}
where order_date > current_date + interval '1 day'
