# Keyless GitHub deploys (PRD R9, R13, D5): Workload Identity pool + provider `github`, and the
# `deployer-staging` service account (also used by SP00's PR previews). Prod deployer is a later task.

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"

  depends_on = [google_project_service.api]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  # Same repo only: fork PRs present a different `repository` claim and never match.
  attribute_condition = "assertion.repository=='${var.github_repository}'"

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.ref"              = "assertion.ref"
    "attribute.environment"      = "assertion.environment"
    "attribute.workflow_ref"     = "assertion.job_workflow_ref"
    "attribute.repository_owner" = "assertion.repository_owner"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deployer_staging" {
  project      = var.project
  account_id   = "deployer-staging"
  display_name = "Onolys GitHub deployer (staging + PR previews)"
}

# Any workflow of the repo may impersonate (staging + previews run on PR branches).
resource "google_service_account_iam_member" "deployer_staging_wif" {
  service_account_id = google_service_account.deployer_staging.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

locals {
  deployer_staging_member = "serviceAccount:${google_service_account.deployer_staging.email}"
  staging_services = {
    api    = module.staging.api_service_name
    worker = module.staging.worker_service_name
  }
  hosting_staging_sites = [
    "projects/${var.project}/sites/${var.app_staging_site_id}",
    "projects/-/sites/${var.app_staging_site_id}",
  ]
}

# --- Staging deploys ---
resource "google_cloud_run_v2_service_iam_member" "deployer_staging_developer" {
  for_each = local.staging_services
  project  = var.project
  location = var.region
  name     = each.value
  role     = "roles/run.developer"
  member   = local.deployer_staging_member
}

# Deploying a revision acts as the runtime SA.
resource "google_service_account_iam_member" "deployer_staging_runtime_user" {
  for_each           = { api = module.staging.api_sa_email, worker = module.staging.worker_sa_email }
  service_account_id = "projects/${var.project}/serviceAccounts/${each.value}"
  role               = "roles/iam.serviceAccountUser"
  member             = local.deployer_staging_member
}

resource "google_artifact_registry_repository_iam_member" "deployer_staging_writer" {
  project    = var.project
  location   = var.region
  repository = google_artifact_registry_repository.onolys.repository_id
  role       = "roles/artifactregistry.writer"
  member     = local.deployer_staging_member
}

# Firebase CLI / REST calls are billed to the project.
resource "google_project_iam_member" "deployer_staging_usage" {
  project = var.project
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = local.deployer_staging_member
}

# Hosting admin limited (IAM condition on resource name) to the staging site and its channels.
resource "google_project_iam_member" "deployer_staging_hosting" {
  project = var.project
  role    = "roles/firebasehosting.admin"
  member  = local.deployer_staging_member

  condition {
    title       = "hosting-app-staging-only"
    description = "Only the ${var.app_staging_site_id} site (and its channels/versions)"
    expression  = join(" || ", [for s in local.hosting_staging_sites : "resource.name.startsWith(\"${s}\")"])
  }
}

# Firestore rules/indexes on the staging database only.
resource "google_project_iam_member" "deployer_staging_index_admin" {
  project = var.project
  role    = "roles/datastore.indexAdmin"
  member  = local.deployer_staging_member

  condition {
    title       = "firestore-staging-only"
    description = "Only the staging database"
    expression  = "resource.name.startsWith(\"${module.staging.firestore_db_resource}\")"
  }
}

resource "google_project_iam_member" "deployer_staging_rules_admin" {
  project = var.project
  role    = "roles/firebaserules.admin"
  member  = local.deployer_staging_member

  condition {
    title       = "firestore-rules-staging-only"
    description = "Rulesets (needed to create) and the staging database release only"
    expression  = "resource.name.startsWith(\"projects/${var.project}/rulesets/\") || resource.name.startsWith(\"projects/${var.project}/releases/cloud.firestore/staging\")"
  }
}

# --- PR previews (SP00 R3, PRD R13) ---
# Cloud Run admin only for services named onolys-pr-* (create/update/delete/IAM of previews).
resource "google_project_iam_member" "deployer_staging_preview_run" {
  project = var.project
  role    = "roles/run.admin"
  member  = local.deployer_staging_member

  condition {
    title       = "cloud-run-preview-services-only"
    description = "Only Cloud Run services named onolys-pr-*"
    expression  = "resource.name.extract(\"/services/{svc}\").startsWith(\"onolys-pr-\")"
  }
}

# Preview services run as api-staging: covered by deployer_staging_runtime_user["api"] above.

output "wif_provider" {
  description = "Value for google-github-actions/auth `workload_identity_provider`."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_staging_email" {
  description = "Value for google-github-actions/auth `service_account` (staging + previews)."
  value       = google_service_account.deployer_staging.email
}
