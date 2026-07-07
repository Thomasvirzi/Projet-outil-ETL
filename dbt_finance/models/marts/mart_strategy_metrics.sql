{{ config(
    partition_by={"field": "start_date", "data_type": "date"},
    cluster_by=["symbol", "strategy_name"]
) }}

with daily as (
    select * from {{ ref('mart_backtest_daily') }}
),

equity_curve as (
    select
        *,
        1 + cumulative_strategy_return as strategy_equity_index,
        max(1 + cumulative_strategy_return) over (
            partition by strategy_name, symbol
            order by date
        ) as running_strategy_peak
    from daily
),

drawdowns as (
    select
        *,
        safe_divide(strategy_equity_index, nullif(running_strategy_peak, 0)) - 1 as drawdown
    from equity_curve
),

trades as (
    select
        strategy_name,
        symbol,
        count(*) as trade_count,
        sum(estimated_fee) as total_estimated_fees,
        sum(estimated_slippage) as total_estimated_slippage,
        sum(estimated_transaction_cost_rate) as total_estimated_transaction_cost_rate
    from {{ ref('mart_backtest_trades') }}
    group by strategy_name, symbol
),

position_runs as (
    select
        *,
        countif(executed_position = 0) over (
            partition by strategy_name, symbol
            order by date
        ) as flat_group
    from daily
),

position_durations as (
    select
        strategy_name,
        symbol,
        flat_group,
        count(*) as position_duration_days
    from position_runs
    where executed_position != 0
    group by strategy_name, symbol, flat_group
),

global_benchmark as (
    select
        date,
        avg(daily_return) as global_benchmark_return
    from {{ ref('stg_benchmarks') }}
    where component_id is null
       or benchmark_type in ('synthetic', 'synthetic_index', 'global')
       or benchmark_id in ('synthetic_commodity_index', 'global_commodities')
    group by date
),

benchmark_curve as (
    select
        date,
        exp(sum(ln(1 + coalesce(global_benchmark_return, 0))) over (
            order by date
        )) - 1 as global_benchmark_cumulative_return
    from global_benchmark
),

aggregated as (
    select
        drawdowns.strategy_name,
        drawdowns.symbol,
        any_value(drawdowns.commodity_id) as commodity_id,
        any_value(drawdowns.commodity_name) as commodity_name,
        min(drawdowns.date) as start_date,
        max(drawdowns.date) as end_date,
        count(*) as trading_days,
        any_value(drawdowns.cumulative_strategy_return having max drawdowns.date) as cumulative_return,
        pow(
            1 + any_value(drawdowns.cumulative_strategy_return having max drawdowns.date),
            safe_divide({{ var('backtest_periods_per_year', 252) }}, count(*))
        ) - 1 as annualized_return,
        stddev_samp(drawdowns.net_strategy_return) * sqrt({{ var('backtest_periods_per_year', 252) }}) as annualized_volatility,
        safe_divide(
            avg(drawdowns.net_strategy_return) * {{ var('backtest_periods_per_year', 252) }},
            nullif(stddev_samp(drawdowns.net_strategy_return) * sqrt({{ var('backtest_periods_per_year', 252) }}), 0)
        ) as sharpe_ratio,
        safe_divide(
            avg(drawdowns.net_strategy_return) * {{ var('backtest_periods_per_year', 252) }},
            nullif(stddev_samp(if(drawdowns.net_strategy_return < 0, drawdowns.net_strategy_return, null)) * sqrt({{ var('backtest_periods_per_year', 252) }}), 0)
        ) as sortino_ratio,
        min(drawdowns.drawdown) as max_drawdown,
        safe_divide(
            pow(
                1 + any_value(drawdowns.cumulative_strategy_return having max drawdowns.date),
                safe_divide({{ var('backtest_periods_per_year', 252) }}, count(*))
            ) - 1,
            nullif(abs(min(drawdowns.drawdown)), 0)
        ) as calmar_ratio,
        safe_divide(
            countif(drawdowns.net_strategy_return > 0),
            nullif(countif(drawdowns.net_strategy_return != 0), 0)
        ) as win_rate,
        safe_divide(
            sum(if(drawdowns.net_strategy_return > 0, drawdowns.net_strategy_return, 0)),
            nullif(abs(sum(if(drawdowns.net_strategy_return < 0, drawdowns.net_strategy_return, 0))), 0)
        ) as profit_factor,
        avg(abs(drawdowns.executed_position)) as avg_exposure,
        max(drawdowns.cumulative_asset_return) as buy_hold_cumulative_return,
        max(benchmark_curve.global_benchmark_cumulative_return) as global_benchmark_cumulative_return
    from drawdowns
    left join benchmark_curve
        on drawdowns.date = benchmark_curve.date
    group by drawdowns.strategy_name, drawdowns.symbol
)

select
    aggregated.*,
    coalesce(trades.trade_count, 0) as trade_count,
    coalesce(avg(position_durations.position_duration_days), 0) as avg_position_duration_days,
    coalesce(trades.total_estimated_fees, 0) as total_estimated_fees,
    coalesce(trades.total_estimated_slippage, 0) as total_estimated_slippage,
    coalesce(trades.total_estimated_transaction_cost_rate, 0) as total_estimated_transaction_cost_rate,
    aggregated.cumulative_return - aggregated.buy_hold_cumulative_return as outperformance_vs_buy_hold,
    aggregated.cumulative_return - coalesce(aggregated.global_benchmark_cumulative_return, 0) as outperformance_vs_global_benchmark
from aggregated
left join trades
    on aggregated.strategy_name = trades.strategy_name
   and aggregated.symbol = trades.symbol
left join position_durations
    on aggregated.strategy_name = position_durations.strategy_name
   and aggregated.symbol = position_durations.symbol
group by
    aggregated.strategy_name,
    aggregated.symbol,
    aggregated.commodity_id,
    aggregated.commodity_name,
    aggregated.start_date,
    aggregated.end_date,
    aggregated.trading_days,
    aggregated.cumulative_return,
    aggregated.annualized_return,
    aggregated.annualized_volatility,
    aggregated.sharpe_ratio,
    aggregated.sortino_ratio,
    aggregated.max_drawdown,
    aggregated.calmar_ratio,
    aggregated.win_rate,
    aggregated.profit_factor,
    aggregated.avg_exposure,
    aggregated.buy_hold_cumulative_return,
    aggregated.global_benchmark_cumulative_return,
    trades.trade_count,
    trades.total_estimated_fees,
    trades.total_estimated_slippage,
    trades.total_estimated_transaction_cost_rate
