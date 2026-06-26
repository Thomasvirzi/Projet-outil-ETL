resource "google_storage_bucket" "artifacts" {
  count = var.create_storage_bucket ? 1 : 0

  project                     = var.project_id
  name                        = local.storage_bucket_name
  location                    = var.location
  uniform_bucket_level_access = true
  labels                      = local.common_labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 30
    }

    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "pipeline_artifacts_object_admin" {
  count = var.create_storage_bucket ? 1 : 0

  bucket = google_storage_bucket.artifacts[0].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.pipeline.email}"
}
