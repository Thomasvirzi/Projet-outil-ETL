select
    article_id,
    count(*) as row_count
from {{ ref('stg_news') }}
group by article_id
having count(*) > 1
