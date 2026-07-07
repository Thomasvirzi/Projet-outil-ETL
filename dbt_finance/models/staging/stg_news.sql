with ranked as (
    select
        cast(article_id as string) as article_id,
        cast(source_id as string) as source_id,
        cast(feed_id as string) as feed_id,
        cast(source as string) as source,
        cast(feed_name as string) as feed_name,
        cast(category as string) as category,
        cast(language as string) as language,
        cast(priority as int64) as priority,
        cast(quality as string) as quality,
        cast(title as string) as title,
        cast(url as string) as url,
        cast(canonical_url as string) as canonical_url,
        coalesce(
            cast(published_at as timestamp),
            cast(fetched_at as timestamp),
            cast(ingested_at as timestamp)
        ) as published_at,
        date(coalesce(
            cast(published_at as timestamp),
            cast(fetched_at as timestamp),
            cast(ingested_at as timestamp)
        )) as published_date,
        cast(summary as string) as summary,
        cast(clean_text as string) as clean_text,
        cast(content_hash as string) as content_hash,
        cast(raw_content_hash as string) as raw_content_hash,
        cast(fetched_at as timestamp) as fetched_at,
        cast(ingested_at as timestamp) as ingested_at,
        row_number() over (
            partition by article_id
            order by ingested_at desc
        ) as row_number_latest
    from {{ ref('landing_news') }}
    where article_id is not null
      and title is not null
)

select * except(row_number_latest)
from ranked
where row_number_latest = 1
