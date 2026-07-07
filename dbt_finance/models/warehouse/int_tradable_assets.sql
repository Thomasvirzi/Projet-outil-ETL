{{ config(
    partition_by={"field": "date", "data_type": "date"},
    cluster_by=["symbol", "category"]
) }}

with commodity_prices as (
    select
        commodity_id,
        commodity_name,
        symbol,
        category,
        date,
        open,
        high,
        low,
        close,
        adjusted_close,
        volume_filled as volume
    from {{ ref('stg_commodity_prices') }}
),

synthetic_index as (
    select
        'COMMODITY_INDEX' as commodity_id,
        any_value(benchmark_name) as commodity_name,
        'COMMODITY_INDEX' as symbol,
        'benchmark' as category,
        date,
        any_value(benchmark_level) as open,
        any_value(benchmark_level) as high,
        any_value(benchmark_level) as low,
        any_value(benchmark_level) as close,
        any_value(benchmark_level) as adjusted_close,
        cast(null as float64) as volume
    from {{ ref('stg_benchmarks') }}
    where benchmark_id = 'synthetic_commodity_index'
      and benchmark_level is not null
    group by date
)

select * from commodity_prices

union all

select * from synthetic_index
