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
