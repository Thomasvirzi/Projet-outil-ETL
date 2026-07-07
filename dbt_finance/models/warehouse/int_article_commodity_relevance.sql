select
    relevance.article_id,
    news.published_date,
    news.source_id,
    news.source,
    news.title,
    relevance.commodity_id,
    relevance.commodity_symbol,
    relevance.commodity_name,
    relevance.similarity_score,
    relevance.is_relevant,
    sentiment.sentiment_score,
    sentiment.novelty_score,
    relevance.calculated_at
from {{ ref('stg_article_commodity_relevance') }} as relevance
left join {{ ref('stg_news') }} as news
    on relevance.article_id = news.article_id
left join {{ ref('stg_news_sentiment') }} as sentiment
    on relevance.article_id = sentiment.article_id
