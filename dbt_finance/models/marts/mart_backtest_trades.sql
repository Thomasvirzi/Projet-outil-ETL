{{ config(
    partition_by={"field": "trade_date", "data_type": "date"},
    cluster_by=["symbol", "strategy_name"]
) }}

select
    commodity_id,
    commodity_name,
    symbol,
    strategy_name,
    date as trade_date,
    close as trade_price,
    previous_position,
    executed_position,
    executed_position - previous_position as position_delta,
    abs(executed_position - previous_position)
    * (
        {{ var('backtest_fee_rate', 0.001) }}
        + {{ var('backtest_slippage_rate', 0.0005) }}
    ) as estimated_transaction_cost_rate,
    abs(executed_position - previous_position)
    * {{ var('backtest_fee_rate', 0.001) }} as estimated_fee,
    abs(executed_position - previous_position)
    * {{ var('backtest_slippage_rate', 0.0005) }} as estimated_slippage,
    case
        when previous_position = 0 and executed_position != 0 then 'open'
        when previous_position != 0 and executed_position = 0 then 'close'
        when previous_position != executed_position then 'rebalance'
    end as trade_type
from {{ ref('mart_backtest_daily') }}
where previous_position != executed_position
