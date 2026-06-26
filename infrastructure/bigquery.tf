resource "google_bigquery_dataset" "raw" {
  dataset_id                 = var.raw_dataset_id
  project                    = var.project_id
  location                   = var.location
  friendly_name              = "Raw data"
  description                = "Raw market, benchmark, RSS, NLP and pipeline log data."
  delete_contents_on_destroy = false
  labels                     = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_bigquery_dataset" "dbt_finance" {
  dataset_id                 = var.dbt_dataset_id
  project                    = var.project_id
  location                   = var.location
  friendly_name              = "dbt finance"
  description                = "dbt landing, staging and warehouse models."
  delete_contents_on_destroy = false
  labels                     = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_bigquery_dataset" "mart" {
  dataset_id                 = var.mart_dataset_id
  project                    = var.project_id
  location                   = var.location
  friendly_name              = "Analytics marts"
  description                = "Final tables used by backtesting and Streamlit."
  delete_contents_on_destroy = false
  labels                     = local.common_labels

  depends_on = [google_project_service.required]
}
