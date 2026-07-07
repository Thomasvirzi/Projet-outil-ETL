select *
from {{ ref('stg_commodity_prices') }}
where date > current_date()
