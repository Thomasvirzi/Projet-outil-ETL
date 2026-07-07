select * from {{ source('raw', 'pipeline_logs_raw') }}
