{{ config(
    partition_by={"field": "date", "data_type": "date"},
    cluster_by=["symbol", "strategy_name"]
) }}

with base as (
    select
        commodity_id,
        commodity_name,
        symbol,
        category,
        strategy_name,
        date,
        close,
        asset_return,
        signal,
        executed_position,
        strategy_return
    from {{ ref('int_daily_returns') }}
),

positioned as (
    select
        *,
        lag(executed_position, 1, 0) over (
            partition by strategy_name, symbol
            order by date
        ) as previous_position
    from base
),

net_returns as (
    select
        *,
        abs(executed_position - previous_position)
        * (
            {{ var('backtest_fee_rate', 0.001) }}
            + {{ var('backtest_slippage_rate', 0.0005) }}
        ) as estimated_transaction_cost_rate,
        abs(executed_position - previous_position)
        * {{ var('backtest_fee_rate', 0.001) }} as estimated_fee,
        abs(executed_position - previous_position)
        * {{ var('backtest_slippage_rate', 0.0005) }} as estimated_slippage
    from positioned
),

cost_adjusted_returns as (
    select
        *,
        coalesce(strategy_return, 0) - coalesce(estimated_transaction_cost_rate, 0) as net_strategy_return
    from net_returns
),

compounding_inputs as (
    select
        *,
        greatest(1 + coalesce(net_strategy_return, 0), 0.000001) as strategy_growth_factor,
        greatest(1 + coalesce(asset_return, 0), 0.000001) as asset_growth_factor
    from cost_adjusted_returns
)

select
    *,
    exp(sum(ln(strategy_growth_factor)) over (
        partition by strategy_name, symbol
        order by date
    )) - 1 as cumulative_strategy_return,
    exp(sum(ln(asset_growth_factor)) over (
        partition by symbol
        order by date
    )) - 1 as cumulative_asset_return,
    sum(estimated_transaction_cost_rate) over (
        partition by strategy_name, symbol
        order by date
    ) as cumulative_estimated_transaction_cost_rate
from compounding_inputs
