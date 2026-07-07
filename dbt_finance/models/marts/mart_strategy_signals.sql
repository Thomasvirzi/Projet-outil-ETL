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
    sma_20,
    sma_50,
    sma_100,
    sma_200,
    bollinger_upper_20d,
    bollinger_lower_20d,
    rsi_14,
    stochastic_rsi_k,
    stochastic_rsi_d,
    macd,
    macd_signal,
    macd_histogram,
    atr_14,
    volatility_20d,
    historical_volatility_20d,
    news_volume,
    news_pressure_score,
    weighted_sentiment_score,
    news_surprise_20d,
    news_acceleration,
    geopolitical_risk_score,
    supply_shock_score,
    weather_risk_score,
    signal
from {{ ref('int_strategy_signals') }}
