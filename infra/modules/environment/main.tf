data "google_project" "this" {
  project_id = var.project
}

locals {
  firestore_db_resource = "projects/${var.project}/databases/${var.database_id}"
}

# --- Firestore (native, location is permanent; PITR off, no backups: PRD R5/D7) ---
resource "google_firestore_database" "db" {
  project                           = var.project
  name                              = var.database_id
  location_id                       = var.region
  type                              = "FIRESTORE_NATIVE"
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_DISABLED"
  delete_protection_state           = var.delete_protection ? "DELETE_PROTECTION_ENABLED" : "DELETE_PROTECTION_DISABLED"
  deletion_policy                   = var.delete_protection ? "ABANDON" : "DELETE"
}

# --- Audio bucket (PRD R6) ---
resource "google_storage_bucket" "audio" {
  project                     = var.project
  name                        = "onolys-audio-${var.env}"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = false
  }

  soft_delete_policy {
    retention_duration_seconds = 0
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age            = 1
      matches_prefix = ["uploads/"]
    }
  }

  cors {
    origin          = var.cors_origins
    method          = ["PUT", "HEAD"]
    response_header = ["Content-Type", "x-goog-content-length-range"]
    max_age_seconds = 3600
  }
}

# --- Cloud Tasks queue (PRD R7) ---
resource "google_cloud_tasks_queue" "steps" {
  project  = var.project
  location = var.region
  name     = "steps-${var.env}"

  rate_limits {
    max_dispatches_per_second = 5
    max_concurrent_dispatches = var.worker_concurrency * var.worker_max_instances
  }

  retry_config {
    max_attempts = 2
    min_backoff  = "5s"
    max_backoff  = "30s"
  }
}

# --- Service accounts (PRD R9) ---
resource "google_service_account" "api" {
  project      = var.project
  account_id   = "api-${var.env}"
  display_name = "Onolys api (${var.env})"
}

resource "google_service_account" "worker" {
  project      = var.project
  account_id   = "worker-${var.env}"
  display_name = "Onolys worker (${var.env})"
}

resource "google_service_account" "tasks_invoker" {
  project      = var.project
  account_id   = "tasks-invoker-${var.env}"
  display_name = "Onolys Cloud Tasks invoker (${var.env})"
}

locals {
  runtime_sas = {
    api    = google_service_account.api.email
    worker = google_service_account.worker.email
  }
}

# datastore.user limited to this env's database by IAM condition on the resource name.
resource "google_project_iam_member" "datastore_user" {
  for_each = local.runtime_sas
  project  = var.project
  role     = "roles/datastore.user"
  member   = "serviceAccount:${each.value}"

  condition {
    title       = "firestore-${var.env}-only"
    description = "Only the ${var.database_id} database"
    expression  = "resource.name == \"${local.firestore_db_resource}\""
  }

  depends_on = [google_firestore_database.db]
}

resource "google_storage_bucket_iam_member" "object_admin" {
  for_each = local.runtime_sas
  bucket   = google_storage_bucket.audio.name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${each.value}"
}

resource "google_cloud_tasks_queue_iam_member" "enqueuer" {
  for_each = local.runtime_sas
  project  = var.project
  location = var.region
  name     = google_cloud_tasks_queue.steps.name
  role     = "roles/cloudtasks.enqueuer"
  member   = "serviceAccount:${each.value}"
}

resource "google_service_account_iam_member" "tasks_invoker_user" {
  for_each           = local.runtime_sas
  service_account_id = google_service_account.tasks_invoker.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${each.value}"
}

# api signs V4 URLs as itself.
resource "google_service_account_iam_member" "api_self_token_creator" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "worker_speech_client" {
  project = var.project
  role    = "roles/speech.client"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

# Speech-to-Text service agent reads audio from the bucket (PRD R9, RESOLVED yes).
resource "google_project_service_identity" "speech" {
  provider = google-beta
  project  = var.project
  service  = "speech.googleapis.com"
}

resource "google_storage_bucket_iam_member" "stt_agent_viewer" {
  bucket = google_storage_bucket.audio.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_project_service_identity.speech.email}"
}
