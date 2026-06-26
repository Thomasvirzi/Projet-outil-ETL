output "project_id" {
  description = "Google Cloud project ID."
  value       = var.project_id
}

output "bigquery_location" {
  description = "BigQuery location used by all datasets."
  value       = var.location
}

output "raw_dataset_id" {
  description = "Raw BigQuery dataset ID."
  value       = google_bigquery_dataset.raw.dataset_id
}

output "dbt_dataset_id" {
  description = "dbt BigQuery dataset ID."
  value       = google_bigquery_dataset.dbt_finance.dataset_id
}

output "mart_dataset_id" {
  description = "Mart BigQuery dataset ID."
  value       = google_bigquery_dataset.mart.dataset_id
}

output "pipeline_service_account_email" {
  description = "Pipeline service account email."
  value       = google_service_account.pipeline.email
}

output "storage_bucket_name" {
  description = "Optional artifacts bucket name."
  value       = var.create_storage_bucket ? google_storage_bucket.artifacts[0].name : null
}
