select
    cast(article_id as string) as article_id,
    cast(positive_probability as float64) as positive_probability,
    cast(neutral_probability as float64) as neutral_probability,
    cast(negative_probability as float64) as negative_probability,
    cast(sentiment_score as float64) as sentiment_score,
    cast(novelty_score as float64) as novelty_score,
    cast(sentiment_model as string) as sentiment_model,
    cast(sentiment_model_version as string) as sentiment_model_version,
    cast(calculated_at as timestamp) as calculated_at
from {{ ref('landing_news_sentiment') }}
where article_id is not null
