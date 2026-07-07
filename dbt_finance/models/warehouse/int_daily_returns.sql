{{ config(
    partition_by={"field": "date", "data_type": "date"},
    cluster_by=["symbol", "strategy_name"]
) }}

select
    commodity_id,
    commodity_name,
    symbol,
    category,
    strategy_name,
    date,
    close,
    simple_return as asset_return,
    signal,
    lag(signal, 1, 0) over (
        partition by strategy_name, symbol
        order by date
    ) as executed_position,
    coalesce(simple_return, 0)
    * lag(signal, 1, 0) over (
        partition by strategy_name, symbol
        order by date
    ) as strategy_return
from {{ ref('int_strategy_signals') }}
