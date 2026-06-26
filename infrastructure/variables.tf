variable "project_id" {
  description = "Google Cloud project ID where resources are created."
  type        = string
}

variable "region" {
  description = "Default Google Cloud region for regional resources."
  type        = string
  default     = "europe-west1"
}

variable "location" {
  description = "BigQuery dataset location. Use a single location for all datasets."
  type        = string
  default     = "EU"
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "dev"
}

variable "raw_dataset_id" {
  description = "BigQuery dataset for raw ingested data."
  type        = string
  default     = "raw"
}

variable "dbt_dataset_id" {
  description = "BigQuery dataset for dbt landing, staging and warehouse models."
  type        = string
  default     = "dbt_finance"
}

variable "mart_dataset_id" {
  description = "BigQuery dataset for final marts used by backtesting and Streamlit."
  type        = string
  default     = "mart"
}

variable "service_account_id" {
  description = "ID of the pipeline service account."
  type        = string
  default     = "etl-commodities-pipeline"
}

variable "service_account_display_name" {
  description = "Display name of the pipeline service account."
  type        = string
  default     = "ELT Commodities Pipeline"
}

variable "create_storage_bucket" {
  description = "Whether to create a Cloud Storage bucket for temporary exports or artifacts."
  type        = bool
  default     = false
}

variable "storage_bucket_name" {
  description = "Optional Cloud Storage bucket name. If null, a default name is generated."
  type        = string
  default     = null
}

variable "labels" {
  description = "Common labels applied to supported resources."
  type        = map(string)
  default = {
    project = "elt-commodities"
  }
}
