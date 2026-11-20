locals {
  apis = [
    "serviceusage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "firestore.googleapis.com",
    "storage.googleapis.com",
    "cloudtasks.googleapis.com",
    "secretmanager.googleapis.com",
    "identitytoolkit.googleapis.com",
    "firebase.googleapis.com",
    "firebasehosting.googleapis.com",
    "firebaserules.googleapis.com",
    "speech.googleapis.com",
    "cloudbilling.googleapis.com",
    "billingbudgets.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "policytroubleshooter.googleapis.com",
  ]
}

resource "google_project_service" "api" {
  for_each = toset(local.apis)

  project            = var.project
  service            = each.value
  disable_on_destroy = false
}

# Shared image repo for both envs. No cleanup policy in v1 (PRD D18).
resource "google_artifact_registry_repository" "onolys" {
  project       = var.project
  location      = var.region
  repository_id = "onolys"
  format        = "DOCKER"
  description   = "Onolys api/worker/admin images"

  depends_on = [google_project_service.api]
}

# Firebase Hosting sites, alongside landing's `onolys` and `onolys-redirect` (not managed here).
resource "google_firebase_hosting_site" "app" {
  provider = google-beta
  project  = var.project
  site_id  = var.app_site_id

  depends_on = [google_project_service.api]
}

resource "google_firebase_hosting_site" "app_staging" {
  provider = google-beta
  project  = var.project
  site_id  = var.app_staging_site_id

  depends_on = [google_project_service.api]
}

# Admin sites (SP07, after launch): gated by var.admin_enabled.
resource "google_firebase_hosting_site" "admin" {
  count    = var.admin_enabled ? 1 : 0
  provider = google-beta
  project  = var.project
  site_id  = var.admin_site_id

  depends_on = [google_project_service.api]
}

resource "google_firebase_hosting_site" "admin_staging" {
  count    = var.admin_enabled ? 1 : 0
  provider = google-beta
  project  = var.project
  site_id  = var.admin_staging_site_id

  depends_on = [google_project_service.api]
}

# Provider-key secret shells (PRD D12): one per llm_secrets/stt_secrets entry, shared by both envs.
# Values are seeded outside state by scripts/seed-secrets.py (PRD D9).
resource "google_secret_manager_secret" "provider" {
  for_each  = merge(var.llm_secrets, var.stt_secrets)
  project   = var.project
  secret_id = each.value

  replication {
    auto {}
  }

  depends_on = [google_project_service.api]
}

locals {
  llm_secret_ids = { for k in keys(var.llm_secrets) : k => google_secret_manager_secret.provider[k].secret_id }
  stt_secret_ids = { for k in keys(var.stt_secrets) : k => google_secret_manager_secret.provider[k].secret_id }
}

module "staging" {
  source = "./modules/environment"

  project                  = var.project
  region                   = var.region
  env                      = "staging"
  database_id              = "staging"
  delete_protection        = false
  worker_concurrency       = var.worker_concurrency
  worker_max_instances     = var.worker_max_instances
  api_max_instances        = 3
  llm_secrets              = local.llm_secret_ids
  stt_secrets              = local.stt_secret_ids
  admin_enabled            = var.admin_enabled
  alerts_enabled           = var.staging_alerts
  notification_channel_ids = [google_monitoring_notification_channel.owner_email.id]
  admin_cors_origins = [
    "https://${var.admin_staging_site_id}.web.app",
    "http://localhost:5173",
  ]
  cors_origins = [
    "https://${var.app_staging_site_id}.web.app",
    "http://localhost:5173",
  ]

  depends_on = [google_project_service.api]
}

# Prod: second instance of the module, isolated from staging by DB, bucket, queue, SAs and secrets (PRD R5-R9, D2).
module "prod" {
  source = "./modules/environment"

  project                  = var.project
  region                   = var.region
  env                      = "prod"
  database_id              = "(default)"
  delete_protection        = true
  worker_concurrency       = var.worker_concurrency
  worker_max_instances     = var.worker_max_instances
  api_max_instances        = 10
  llm_secrets              = local.llm_secret_ids
  stt_secrets              = local.stt_secret_ids
  admin_enabled            = var.admin_enabled
  alerts_enabled           = true
  notification_channel_ids = [google_monitoring_notification_channel.owner_email.id]
  admin_cors_origins       = ["https://${var.admin_site_id}.web.app"]
  cors_origins             = ["https://app.onolys.com"]

  depends_on = [google_project_service.api]
}
