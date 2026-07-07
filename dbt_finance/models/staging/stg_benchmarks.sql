with ranked as (
    select
        cast(date as date) as date,
        cast(benchmark_id as string) as benchmark_id,
        cast(benchmark_type as string) as benchmark_type,
        cast(benchmark_name as string) as benchmark_name,
        cast(component_id as string) as component_id,
        cast(component_symbol as string) as component_symbol,
        cast(component_name as string) as component_name,
        cast(category as string) as category,
        cast(priority as string) as priority,
        cast(close_price as float64) as close_price,
        cast(benchmark_level as float64) as benchmark_level,
        cast(daily_return as float64) as daily_return,
        cast(drawdown as float64) as drawdown,
        cast(actual_weight as float64) as actual_weight,
        cast(target_weight as float64) as target_weight,
        cast(rebalance_executed as bool) as rebalance_executed,
        cast(source as string) as source,
        cast(methodology as string) as methodology,
        cast(ingested_at as timestamp) as ingested_at,
        row_number() over (
            partition by date, benchmark_id, coalesce(component_id, '')
            order by ingested_at desc
        ) as row_number_latest
    from {{ ref('landing_benchmarks') }}
    where date is not null
      and benchmark_id is not null
)

select * except(row_number_latest)
from ranked
where row_number_latest = 1
