select
    cast(article_id as string) as article_id,
    cast(commodity_id as string) as commodity_id,
    cast(commodity_symbol as string) as commodity_symbol,
    cast(commodity_name as string) as commodity_name,
    cast(commodity_description as string) as commodity_description,
    cast(similarity_score as float64) as similarity_score,
    cast(is_relevant as bool) as is_relevant,
    cast(relevance_threshold as float64) as relevance_threshold,
    cast(embedding_model as string) as embedding_model,
    cast(calculated_at as timestamp) as calculated_at
from {{ ref('landing_article_commodity_relevance') }}
where article_id is not null
  and commodity_id is not null
