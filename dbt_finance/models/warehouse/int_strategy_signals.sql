{{ config(
    partition_by={"field": "date", "data_type": "date"},
    cluster_by=["symbol", "strategy_name"]
) }}

with technical as (
    select * from {{ ref('int_technical_indicators') }}
),

news as (
    select * from {{ ref('int_commodity_news_features') }}
),

joined as (
    select
        technical.commodity_id,
        technical.commodity_name,
        technical.symbol,
        technical.category,
        technical.date,
        technical.close,
        technical.low,
        technical.simple_return,
        technical.sma_20,
        technical.sma_50,
        technical.sma_100,
        technical.sma_200,
        technical.bollinger_upper_20d,
        technical.bollinger_lower_20d,
        technical.rsi_14,
        technical.stochastic_rsi_k,
        technical.stochastic_rsi_d,
        technical.macd,
        technical.macd_signal,
        technical.macd_histogram,
        technical.atr_14,
        technical.volatility_20d,
        technical.historical_volatility_20d,
        max(technical.close) over (
            partition by technical.symbol
            order by technical.date
            rows between 20 preceding and 1 preceding
        ) as previous_high_20d,
        min(technical.close) over (
            partition by technical.symbol
            order by technical.date
            rows between 10 preceding and 1 preceding
        ) as previous_low_10d,
        coalesce(news.news_volume, 0) as news_volume,
        coalesce(news.news_pressure_score, 0) as news_pressure_score,
        coalesce(news.weighted_sentiment_score, 0) as weighted_sentiment_score,
        coalesce(news.news_surprise_20d, 0) as news_surprise_20d,
        coalesce(news.news_acceleration, 0) as news_acceleration,
        coalesce(news.geopolitical_risk_score, 0) as geopolitical_risk_score,
        coalesce(news.supply_shock_score, 0) as supply_shock_score,
        coalesce(news.weather_risk_score, 0) as weather_risk_score
    from technical
    left join news
        on technical.commodity_id = news.commodity_id
       and technical.date = news.date
),

breakout_events as (
    select
        *,
        previous_high_20d is not null
          and close > previous_high_20d as breakout_entry_event,
        previous_low_10d is not null
          and close < previous_low_10d as breakout_exit_event
    from joined
),

breakout_state as (
    select
        *,
        max(if(breakout_entry_event, date, null)) over (
            partition by symbol
            order by date
            rows between unbounded preceding and current row
        ) as last_breakout_entry_date,
        max(if(breakout_exit_event, date, null)) over (
            partition by symbol
            order by date
            rows between unbounded preceding and current row
        ) as last_breakout_exit_date
    from breakout_events
),

strategy_rules as (
    select
        *,
        1 as buy_and_hold_signal,
        case
            when sma_20 >= sma_50 then 1
            else 0
        end as moving_average_cross_signal,
        case
            when sma_20 >= sma_50
              and coalesce(stochastic_rsi_k, 0) >= 20
              and coalesce(stochastic_rsi_d, 100) <= 80
            then 1
            else 0
        end as moving_average_stoch_rsi_signal,
        case
            when close > sma_20
              and sma_20 >= sma_50
              and coalesce(rsi_14, 50) between 30 and 75
              and weighted_sentiment_score >= -0.15
              and geopolitical_risk_score < 0.75
              and supply_shock_score < 0.75
            then 1
            else 0
        end as technical_news_filter_signal,
        case
            when last_breakout_entry_date is not null
              and (
                last_breakout_exit_date is null
                or last_breakout_entry_date > last_breakout_exit_date
              )
            then 1
            else 0
        end as breakout_20d_signal
    from breakout_state
)

select
    * except(
        previous_high_20d,
        previous_low_10d,
        breakout_entry_event,
        breakout_exit_event,
        last_breakout_entry_date,
        last_breakout_exit_date,
        buy_and_hold_signal,
        moving_average_cross_signal,
        moving_average_stoch_rsi_signal,
        technical_news_filter_signal,
        breakout_20d_signal
    ),
    buy_and_hold_signal as signal,
    'buy_and_hold' as strategy_name
from strategy_rules

union all

select
    * except(
        previous_high_20d,
        previous_low_10d,
        breakout_entry_event,
        breakout_exit_event,
        last_breakout_entry_date,
        last_breakout_exit_date,
        buy_and_hold_signal,
        moving_average_cross_signal,
        moving_average_stoch_rsi_signal,
        technical_news_filter_signal,
        breakout_20d_signal
    ),
    moving_average_cross_signal as signal,
    'moving_average_cross' as strategy_name
from strategy_rules

union all

select
    * except(
        previous_high_20d,
        previous_low_10d,
        breakout_entry_event,
        breakout_exit_event,
        last_breakout_entry_date,
        last_breakout_exit_date,
        buy_and_hold_signal,
        moving_average_cross_signal,
        moving_average_stoch_rsi_signal,
        technical_news_filter_signal,
        breakout_20d_signal
    ),
    moving_average_stoch_rsi_signal as signal,
    'moving_average_stoch_rsi' as strategy_name
from strategy_rules

union all

select
    * except(
        previous_high_20d,
        previous_low_10d,
        breakout_entry_event,
        breakout_exit_event,
        last_breakout_entry_date,
        last_breakout_exit_date,
        buy_and_hold_signal,
        moving_average_cross_signal,
        moving_average_stoch_rsi_signal,
        technical_news_filter_signal,
        breakout_20d_signal
    ),
    technical_news_filter_signal as signal,
    'technical_news_filter' as strategy_name
from strategy_rules

union all

select
    * except(
        previous_high_20d,
        previous_low_10d,
        breakout_entry_event,
        breakout_exit_event,
        last_breakout_entry_date,
        last_breakout_exit_date,
        buy_and_hold_signal,
        moving_average_cross_signal,
        moving_average_stoch_rsi_signal,
        technical_news_filter_signal,
        breakout_20d_signal
    ),
    breakout_20d_signal as signal,
    'breakout_20d' as strategy_name
from strategy_rules
