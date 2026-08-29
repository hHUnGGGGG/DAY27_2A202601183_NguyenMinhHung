-- Protected Mart: Deduplicates active customer dimension records to prevent revenue inflation
with completed_orders as (
    select *
    from {{ ref('stg_orders') }}
    where status = 'completed'
),
deduped_customers as (
    select
        customer_id,
        country,
        tier,
        row_number() over (partition by customer_id order by valid_from desc) as rn
    from {{ ref('stg_customers') }}
    where is_active = true
),
active_customers as (
    select *
    from deduped_customers
    where rn = 1
)
select
    o.order_date,
    count(*) as completed_order_rows,
    sum(o.amount_usd) as daily_revenue
from completed_orders o
left join active_customers c
    on o.customer_id = c.customer_id
group by 1
order by 1
