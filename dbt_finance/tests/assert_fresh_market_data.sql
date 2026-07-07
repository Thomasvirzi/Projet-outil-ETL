select *
from (
    select max(date) as max_market_date
    from {{ ref('stg_commodity_prices') }}
)
where max_market_date < date_sub(current_date(), interval 7 day)
