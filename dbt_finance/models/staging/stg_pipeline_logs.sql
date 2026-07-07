select
    cast(null as string) as run_id,
    cast(null as string) as task_name,
    cast(null as string) as status,
    cast(null as timestamp) as started_at,
    cast(null as timestamp) as finished_at,
    cast(null as float64) as duration_seconds,
    cast(null as int64) as rows_processed,
    cast(null as string) as message
from {{ ref('landing_pipeline_logs') }}
where false
