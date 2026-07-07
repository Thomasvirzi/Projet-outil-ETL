select * from {{ source('raw', 'market_data_raw') }}
