select * from {{ source('raw', 'news_sentiment_raw') }}
