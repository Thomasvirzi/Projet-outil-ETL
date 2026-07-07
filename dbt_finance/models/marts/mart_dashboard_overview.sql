{{ config(
    partition_by={"field": "latest_date", "data_type": "date"},
    cluster_by=["symbol", "strategy_name"]
) }}

with latest_market as (
    select *
    from {{ ref('mart_strategy_signals') }}
    qualify row_number() over (
        partition by symbol
        order by date desc
    ) = 1
),

metrics as (
    select * from {{ ref('mart_strategy_metrics') }}
)

select
    latest_market.commodity_id,
    latest_market.commodity_name,
    latest_market.symbol,
    latest_market.category,
    latest_market.date as latest_date,
    latest_market.close as latest_close,
    latest_market.signal as latest_signal,
    latest_market.news_volume,
    latest_market.news_pressure_score,
    latest_market.weighted_sentiment_score,
    latest_market.news_acceleration,
    latest_market.geopolitical_risk_score,
    latest_market.supply_shock_score,
    latest_market.weather_risk_score,
    metrics.strategy_name,
    metrics.cumulative_return,
    metrics.annualized_return,
    metrics.annualized_volatility,
    metrics.sharpe_ratio,
    metrics.sortino_ratio,
    metrics.max_drawdown,
    metrics.calmar_ratio,
    metrics.win_rate,
    metrics.profit_factor,
    metrics.trade_count,
    metrics.total_estimated_transaction_cost_rate,
    metrics.outperformance_vs_buy_hold,
    metrics.outperformance_vs_global_benchmark,
    metrics.avg_exposure
from latest_market
left join metrics
    on latest_market.symbol = metrics.symbol
   and latest_market.strategy_name = metrics.strategy_name
