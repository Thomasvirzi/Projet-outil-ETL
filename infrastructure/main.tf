locals {
  common_labels = merge(
    var.labels,
    {
      environment = var.environment
      managed_by  = "terraform"
    }
  )

  required_apis = toset([
    "bigquery.googleapis.com",
    "bigquerystorage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com"
  ])

  storage_bucket_name = coalesce(
    var.storage_bucket_name,
    "${var.project_id}-elt-commodities-artifacts"
  )
}

resource "google_project_service" "required" {
  for_each = local.required_apis

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
