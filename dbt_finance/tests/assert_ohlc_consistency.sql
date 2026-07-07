select *
from {{ ref('stg_commodity_prices') }}
where high < greatest(open, low, close)
   or low > least(open, high, close)
   or close is null
