select
    cast(article_id as string) as article_id,
    cast(embedding as string) as embedding,
    cast(embedding_dimension as int64) as embedding_dimension,
    cast(embedding_model as string) as embedding_model,
    cast(embedding_model_version as string) as embedding_model_version,
    cast(created_at as timestamp) as created_at
from {{ ref('landing_news_embeddings') }}
where article_id is not null
