project_id  = "your-gcp-project-id"
region      = "europe-west1"
location    = "EU"
environment = "dev"

raw_dataset_id  = "raw"
dbt_dataset_id  = "dbt_finance"
mart_dataset_id = "mart"

service_account_id           = "etl-commodities-pipeline"
service_account_display_name = "ELT Commodities Pipeline"

create_storage_bucket = false
storage_bucket_name   = null
