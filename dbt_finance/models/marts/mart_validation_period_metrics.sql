{{ config(
    partition_by={"field": "start_date", "data_type": "date"},
    cluster_by=["validation_period", "symbol", "strategy_name"]
) }}

with daily as (
    select
        *,
        case
            when date between date '2020-01-01' and date '2023-12-31' then 'calibration'
            when date between date '2024-01-01' and date '2024-12-31' then 'validation'
            when date >= date '2025-01-01' then 'test'
            else 'out_of_scope'
        end as validation_period,
        case
            when date between date '2020-01-01' and date '2024-12-31' then true
            else false
        end as is_optimization_allowed
    from {{ ref('mart_backtest_daily') }}
),

scoped as (
    select *
    from daily
    where validation_period != 'out_of_scope'
),

compounding_inputs as (
    select
        *,
        greatest(1 + coalesce(net_strategy_return, 0), 0.000001) as period_strategy_growth_factor,
        greatest(1 + coalesce(asset_return, 0), 0.000001) as period_asset_growth_factor
    from scoped
),

equity_curve as (
    select
        *,
        exp(sum(ln(period_strategy_growth_factor)) over (
            partition by validation_period, strategy_name, symbol
            order by date
        )) - 1 as period_cumulative_return,
        exp(sum(ln(period_asset_growth_factor)) over (
            partition by validation_period, symbol
            order by date
        )) - 1 as period_buy_hold_cumulative_return
    from compounding_inputs
),

drawdowns as (
    select
        *,
        safe_divide(
            1 + period_cumulative_return,
            nullif(max(1 + period_cumulative_return) over (
                partition by validation_period, strategy_name, symbol
                order by date
            ), 0)
        ) - 1 as period_drawdown
    from equity_curve
),

trades as (
    select
        case
            when trade_date between date '2020-01-01' and date '2023-12-31' then 'calibration'
            when trade_date between date '2024-01-01' and date '2024-12-31' then 'validation'
            when trade_date >= date '2025-01-01' then 'test'
            else 'out_of_scope'
        end as validation_period,
        strategy_name,
        symbol,
        count(*) as trade_count,
        sum(estimated_fee) as total_estimated_fees,
        sum(estimated_slippage) as total_estimated_slippage,
        sum(estimated_transaction_cost_rate) as total_estimated_transaction_cost_rate
    from {{ ref('mart_backtest_trades') }}
    group by validation_period, strategy_name, symbol
),

aggregated as (
    select
        validation_period,
        any_value(is_optimization_allowed) as is_optimization_allowed,
        strategy_name,
        symbol,
        any_value(commodity_id) as commodity_id,
        any_value(commodity_name) as commodity_name,
        min(date) as start_date,
        max(date) as end_date,
        count(*) as trading_days,
        any_value(period_cumulative_return having max date) as cumulative_return,
        pow(
            1 + any_value(period_cumulative_return having max date),
            safe_divide({{ var('backtest_periods_per_year', 252) }}, count(*))
        ) - 1 as annualized_return,
        stddev_samp(net_strategy_return) * sqrt({{ var('backtest_periods_per_year', 252) }}) as annualized_volatility,
        safe_divide(
            avg(net_strategy_return) * {{ var('backtest_periods_per_year', 252) }},
            nullif(stddev_samp(net_strategy_return) * sqrt({{ var('backtest_periods_per_year', 252) }}), 0)
        ) as sharpe_ratio,
        safe_divide(
            avg(net_strategy_return) * {{ var('backtest_periods_per_year', 252) }},
            nullif(stddev_samp(if(net_strategy_return < 0, net_strategy_return, null)) * sqrt({{ var('backtest_periods_per_year', 252) }}), 0)
        ) as sortino_ratio,
        min(period_drawdown) as max_drawdown,
        safe_divide(
            pow(
                1 + any_value(period_cumulative_return having max date),
                safe_divide({{ var('backtest_periods_per_year', 252) }}, count(*))
            ) - 1,
            nullif(abs(min(period_drawdown)), 0)
        ) as calmar_ratio,
        safe_divide(countif(net_strategy_return > 0), nullif(countif(net_strategy_return != 0), 0)) as win_rate,
        safe_divide(
            sum(if(net_strategy_return > 0, net_strategy_return, 0)),
            nullif(abs(sum(if(net_strategy_return < 0, net_strategy_return, 0))), 0)
        ) as profit_factor,
        any_value(period_buy_hold_cumulative_return having max date) as buy_hold_cumulative_return
    from drawdowns
    group by validation_period, strategy_name, symbol
),

ranked as (
    select
        aggregated.*,
        coalesce(trades.trade_count, 0) as trade_count,
        coalesce(trades.total_estimated_fees, 0) as total_estimated_fees,
        coalesce(trades.total_estimated_slippage, 0) as total_estimated_slippage,
        coalesce(trades.total_estimated_transaction_cost_rate, 0) as total_estimated_transaction_cost_rate,
        percent_rank() over (
            partition by aggregated.validation_period
            order by aggregated.cumulative_return
        ) as return_rank,
        percent_rank() over (
            partition by aggregated.validation_period
            order by aggregated.sharpe_ratio
        ) as sharpe_rank,
        percent_rank() over (
            partition by aggregated.validation_period
            order by aggregated.max_drawdown
        ) as drawdown_rank,
        percent_rank() over (
            partition by aggregated.validation_period
            order by coalesce(trades.trade_count, 0)
        ) as activity_rank
    from aggregated
    left join trades
        on aggregated.validation_period = trades.validation_period
       and aggregated.strategy_name = trades.strategy_name
       and aggregated.symbol = trades.symbol
)

select
    *,
    0.35 * return_rank
    + 0.35 * sharpe_rank
    + 0.20 * drawdown_rank
    - 0.10 * activity_rank as robust_selection_score
from ranked
