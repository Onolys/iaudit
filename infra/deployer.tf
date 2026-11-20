# Keyless GitHub deploys (PRD R9, R13, D5): Workload Identity pool + provider `github`, and the
# `deployer-staging` service account (also used by SP00's PR previews) and `deployer-prod` (production environment only).

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
  # Admin entries (SP07) exist only while admin_enabled (staging) is true; nothing changes while it is false.
  staging_services = merge(
    {
      api    = module.staging.api_service_name
      worker = module.staging.worker_service_name
    },
    var.admin_enabled["staging"] ? { admin = module.staging.admin_backend_service_name } : {},
  )
  staging_runtime_sas = merge(
    { api = module.staging.api_sa_email, worker = module.staging.worker_sa_email },
    var.admin_enabled["staging"] ? { admin = module.staging.admin_backend_sa_email } : {},
  )
  hosting_staging_sites = concat(
    [
      "projects/${var.project}/sites/${var.app_staging_site_id}",
      "projects/-/sites/${var.app_staging_site_id}",
    ],
    var.admin_enabled["staging"] ? [
      "projects/${var.project}/sites/${var.admin_staging_site_id}",
      "projects/-/sites/${var.admin_staging_site_id}",
    ] : [],
  )
}

# firebase-tools reads the Firebase project (firebase.projects.get) before every deploy. That permission is
# project level, so the Hosting grant (conditioned on site resource names) never covers it. A single-permission
# custom role keeps it narrower than roles/firebase.viewer.
resource "google_project_iam_custom_role" "firebase_project_get" {
  project     = var.project
  role_id     = "firebaseProjectGet"
  title       = "Firebase project get (deployers)"
  description = "Read the Firebase project; required by firebase-tools deploy."
  permissions = ["firebase.projects.get"]
}

resource "google_project_iam_member" "deployer_staging_firebase_project_get" {
  project = var.project
  role    = google_project_iam_custom_role.firebase_project_get.name
  member  = local.deployer_staging_member
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
  for_each           = local.staging_runtime_sas
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
    description = "Only the ${var.app_staging_site_id}${var.admin_enabled["staging"] ? " and ${var.admin_staging_site_id}" : ""} site${var.admin_enabled["staging"] ? "s" : ""} (and ${var.admin_enabled["staging"] ? "their" : "its"} channels/versions)"
    expression  = join(" || ", [for s in local.hosting_staging_sites : "resource.name.startsWith(\"${s}\")"])
  }
}

# Firestore rules/indexes. Indexes are limited to the staging database by condition. Rules are project level on
# purpose: firebase-tools calls rulesets.test/create on the bare project resource, and IAM conditions on
# resource.name (tried: project id and project number) never matched it (run 44810006543, 403 on :test).
# Trade-off: deployer-staging could release prod rules (releases/cloud.firestore). Accepted: same GitHub repo
# trust, and the workflow only targets `firestore:staging`. See ADR 0022 (D5).
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

# --- deployer-prod (PRD R9, R13, D6) ---
resource "google_service_account" "deployer_prod" {
  project      = var.project
  account_id   = "deployer-prod"
  display_name = "Onolys GitHub deployer (prod)"
}

# Only jobs running in the GitHub `production` environment may impersonate. The provider condition
# already pins the repository; a staging job (environment `staging` or none) never matches this principal.
resource "google_service_account_iam_member" "deployer_prod_wif" {
  service_account_id = google_service_account.deployer_prod.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.environment/production"
}

locals {
  deployer_prod_member = "serviceAccount:${google_service_account.deployer_prod.email}"
  prod_services = merge(
    {
      api    = module.prod.api_service_name
      worker = module.prod.worker_service_name
    },
    var.admin_enabled["prod"] ? { admin = module.prod.admin_backend_service_name } : {},
  )
  prod_runtime_sas = merge(
    { api = module.prod.api_sa_email, worker = module.prod.worker_sa_email },
    var.admin_enabled["prod"] ? { admin = module.prod.admin_backend_sa_email } : {},
  )
  # Exact site or its children only: a bare startsWith would also match `onolys-app-staging`
  # (and `onolys-admin` would match `onolys-admin-staging`).
  hosting_prod_sites = concat(
    [var.app_site_id],
    var.admin_enabled["prod"] ? [var.admin_site_id] : [],
  )
  hosting_prod_expr = join(" || ", flatten([
    for id in local.hosting_prod_sites : [
      for s in ["projects/${var.project}/sites/${id}", "projects/-/sites/${id}"] :
      ["resource.name == \"${s}\"", "resource.name.startsWith(\"${s}/\")"]
    ]
  ]))
}

resource "google_cloud_run_v2_service_iam_member" "deployer_prod_developer" {
  for_each = local.prod_services
  project  = var.project
  location = var.region
  name     = each.value
  role     = "roles/run.developer"
  member   = local.deployer_prod_member
}

resource "google_service_account_iam_member" "deployer_prod_runtime_user" {
  for_each           = local.prod_runtime_sas
  service_account_id = "projects/${var.project}/serviceAccounts/${each.value}"
  role               = "roles/iam.serviceAccountUser"
  member             = local.deployer_prod_member
}

# Prod pulls the image built by staging CI; it never pushes.
resource "google_artifact_registry_repository_iam_member" "deployer_prod_reader" {
  project    = var.project
  location   = var.region
  repository = google_artifact_registry_repository.onolys.repository_id
  role       = "roles/artifactregistry.reader"
  member     = local.deployer_prod_member
}

resource "google_project_iam_member" "deployer_prod_usage" {
  project = var.project
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = local.deployer_prod_member
}

resource "google_project_iam_member" "deployer_prod_firebase_project_get" {
  project = var.project
  role    = google_project_iam_custom_role.firebase_project_get.name
  member  = local.deployer_prod_member
}

resource "google_project_iam_member" "deployer_prod_hosting" {
  project = var.project
  role    = "roles/firebasehosting.admin"
  member  = local.deployer_prod_member

  condition {
    title       = "hosting-app-prod-only"
    description = "Only the ${var.app_site_id}${var.admin_enabled["prod"] ? " and ${var.admin_site_id}" : ""} site${var.admin_enabled["prod"] ? "s" : ""} (and ${var.admin_enabled["prod"] ? "their" : "its"} channels/versions)"
    expression  = local.hosting_prod_expr
  }
}

resource "google_project_iam_member" "deployer_prod_index_admin" {
  project = var.project
  role    = "roles/datastore.indexAdmin"
  member  = local.deployer_prod_member

  condition {
    title       = "firestore-prod-only"
    description = "Only the (default) database"
    expression  = "resource.name.startsWith(\"${module.prod.firestore_db_resource}\")"
  }
}

resource "google_project_iam_member" "deployer_prod_rules_admin" {
  project = var.project
  role    = "roles/firebaserules.admin"
  member  = local.deployer_prod_member
}

output "deployer_prod_email" {
  description = "Value for google-github-actions/auth `service_account` (prod, `production` environment jobs only)."
  value       = google_service_account.deployer_prod.email
}
