{{ config(
    cluster_by=["validation_period", "symbol"]
) }}

with period_metrics as (
    select * from {{ ref('mart_validation_period_metrics') }}
),

technical as (
    select *
    from period_metrics
    where strategy_name = 'moving_average_cross'
),

rss as (
    select *
    from period_metrics
    where strategy_name = 'technical_news_filter'
)

select
    rss.validation_period,
    rss.symbol,
    rss.commodity_id,
    rss.commodity_name,
    rss.cumulative_return as rss_cumulative_return,
    technical.cumulative_return as technical_cumulative_return,
    rss.cumulative_return - technical.cumulative_return as return_delta,
    rss.sharpe_ratio as rss_sharpe_ratio,
    technical.sharpe_ratio as technical_sharpe_ratio,
    rss.sharpe_ratio - technical.sharpe_ratio as sharpe_delta,
    rss.max_drawdown as rss_max_drawdown,
    technical.max_drawdown as technical_max_drawdown,
    rss.max_drawdown - technical.max_drawdown as drawdown_delta,
    (
        rss.cumulative_return > technical.cumulative_return
        and rss.sharpe_ratio >= technical.sharpe_ratio
        and rss.max_drawdown >= technical.max_drawdown
    ) as rss_adds_value
from rss
inner join technical
    on rss.validation_period = technical.validation_period
   and rss.symbol = technical.symbol
