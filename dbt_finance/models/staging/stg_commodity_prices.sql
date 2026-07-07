with ranked as (
    select
        cast(date as date) as date,
        cast(commodity_id as string) as commodity_id,
        cast(commodity_name as string) as commodity_name,
        cast(label_fr as string) as label_fr,
        cast(symbol as string) as symbol,
        cast(category as string) as category,
        cast(priority as string) as priority,
        cast(currency as string) as currency,
        cast(open as float64) as open,
        cast(high as float64) as high,
        cast(low as float64) as low,
        cast(close as float64) as close,
        cast(adjusted_close as float64) as adjusted_close,
        cast(volume as float64) as volume,
        cast(volume_filled as float64) as volume_filled,
        cast(source as string) as source,
        cast(ingested_at as timestamp) as ingested_at,
        row_number() over (
            partition by symbol, date
            order by ingested_at desc
        ) as row_number_latest
    from {{ ref('landing_market_data') }}
    where symbol is not null
      and date is not null
)

select * except(row_number_latest)
from ranked
where row_number_latest = 1
