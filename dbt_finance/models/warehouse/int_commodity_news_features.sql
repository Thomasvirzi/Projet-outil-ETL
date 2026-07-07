{{ config(
    materialized='table',
    partition_by={"field": "date", "data_type": "date"},
    cluster_by=["commodity_id", "commodity_symbol"]
) }}

select
    cast(commodity_id as string) as commodity_id,
    cast(commodity_symbol as string) as commodity_symbol,
    cast(date as date) as date,
    cast(news_volume as int64) as news_volume,
    cast(relevant_news_volume as int64) as relevant_news_volume,
    cast(weighted_sentiment_score as float64) as weighted_sentiment_score,
    cast(avg_relevance_score as float64) as avg_relevance_score,
    cast(avg_novelty_score as float64) as avg_novelty_score,
    cast(sentiment_dispersion as float64) as sentiment_dispersion,
    cast(freshness_score as float64) as freshness_score,
    cast(source_weight as float64) as source_weight,
    cast(news_pressure_score as float64) as news_pressure_score,
    cast(news_surprise_20d as float64) as news_surprise_20d,
    cast(news_acceleration as float64) as news_acceleration,
    cast(geopolitical_risk_score as float64) as geopolitical_risk_score,
    cast(supply_shock_score as float64) as supply_shock_score,
    cast(weather_risk_score as float64) as weather_risk_score,
    cast(calculated_at as timestamp) as calculated_at
from {{ ref('landing_news_features') }}
