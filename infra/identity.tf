# Identity Platform (PRD R4): one user pool for both envs; data isolation is by Firestore DB/bucket.
# Google sign-in and email templates are owner console steps (OAuth client cannot be created by API).

locals {
  # Firebase project defaults (kept: the project was created with them) + PRD R4 hosts.
  authorized_domains = distinct(concat(
    [
      "localhost",
      "${var.project}.firebaseapp.com",
      "${var.project}.web.app",
      "app.onolys.com",
      "${var.app_site_id}.web.app",
      "${var.app_staging_site_id}.web.app",
    ],
    var.admin_enabled ? ["admin.onolys.com", "${var.admin_site_id}.web.app", "${var.admin_staging_site_id}.web.app"] : [],
  ))
}

resource "google_identity_platform_config" "default" {
  project            = var.project
  authorized_domains = local.authorized_domains

  # Domains are only ever added after creation (scripts/identity-config.py, incl. preview channel
  # hosts the SP00 workflow adds); Terraform must not prune them.
  lifecycle {
    ignore_changes = [authorized_domains]
  }

  sign_in {
    allow_duplicate_emails = false

    email {
      enabled           = true
      password_required = true
    }

    phone_number {
      enabled = false
    }
  }

  multi_tenant {
    allow_tenants = false
  }

  client {
    permissions {
      disabled_user_signup   = false # open sign-up
      disabled_user_deletion = false
    }
  }

  mfa {
    state = "DISABLED"
  }

  depends_on = [google_project_service.api]
}

# The provider has no password policy / email-enumeration-protection fields: REST-patch them.
resource "terraform_data" "identity_policy" {
  triggers_replace = [
    filesha256("${path.module}/scripts/identity-config.py"),
    google_identity_platform_config.default.id,
    join(",", local.authorized_domains),
  ]

  provisioner "local-exec" {
    command = "python3 ${path.module}/scripts/identity-config.py ${join(" ", [for d in local.authorized_domains : "--add-domain ${d}"])}"
  }
}

# One Firebase web app per host.
resource "google_firebase_web_app" "app" {
  provider        = google-beta
  project         = var.project
  display_name    = "onolys-app"
  deletion_policy = "DELETE"

  depends_on = [google_project_service.api]
}

resource "google_firebase_web_app" "app_staging" {
  provider        = google-beta
  project         = var.project
  display_name    = "onolys-app-staging"
  deletion_policy = "DELETE"

  depends_on = [google_project_service.api]
}

resource "google_firebase_web_app" "admin" {
  count           = var.admin_enabled ? 1 : 0
  provider        = google-beta
  project         = var.project
  display_name    = "onolys-admin"
  deletion_policy = "DELETE"

  depends_on = [google_project_service.api]
}

resource "google_firebase_web_app" "admin_staging" {
  count           = var.admin_enabled ? 1 : 0
  provider        = google-beta
  project         = var.project
  display_name    = "onolys-admin-staging"
  deletion_policy = "DELETE"

  depends_on = [google_project_service.api]
}

data "google_firebase_web_app_config" "app" {
  provider   = google-beta
  project    = var.project
  web_app_id = google_firebase_web_app.app.app_id
}

data "google_firebase_web_app_config" "app_staging" {
  provider   = google-beta
  project    = var.project
  web_app_id = google_firebase_web_app.app_staging.app_id
}

data "google_firebase_web_app_config" "admin" {
  count      = var.admin_enabled ? 1 : 0
  provider   = google-beta
  project    = var.project
  web_app_id = google_firebase_web_app.admin[0].app_id
}

data "google_firebase_web_app_config" "admin_staging" {
  count      = var.admin_enabled ? 1 : 0
  provider   = google-beta
  project    = var.project
  web_app_id = google_firebase_web_app.admin_staging[0].app_id
}

# Public web config per build (Firebase web apiKey is a public identifier; access is enforced by Identity Platform + rules).
output "web_env_staging" {
  description = "VITE_* build vars for the staging web app (site onolys-app-staging)."
  value = {
    VITE_FIREBASE_API_KEY             = data.google_firebase_web_app_config.app_staging.api_key
    VITE_FIREBASE_AUTH_DOMAIN         = data.google_firebase_web_app_config.app_staging.auth_domain
    VITE_FIREBASE_PROJECT_ID          = var.project
    VITE_FIREBASE_APP_ID              = google_firebase_web_app.app_staging.app_id
    VITE_FIREBASE_STORAGE_BUCKET      = data.google_firebase_web_app_config.app_staging.storage_bucket
    VITE_FIREBASE_MESSAGING_SENDER_ID = data.google_firebase_web_app_config.app_staging.messaging_sender_id
    VITE_FIRESTORE_DATABASE           = module.staging.database_id
  }
}

output "web_env_prod" {
  description = "VITE_* build vars for the prod web app (site onolys-app). Firestore DB is (default)."
  value = {
    VITE_FIREBASE_API_KEY             = data.google_firebase_web_app_config.app.api_key
    VITE_FIREBASE_AUTH_DOMAIN         = data.google_firebase_web_app_config.app.auth_domain
    VITE_FIREBASE_PROJECT_ID          = var.project
    VITE_FIREBASE_APP_ID              = google_firebase_web_app.app.app_id
    VITE_FIREBASE_STORAGE_BUCKET      = data.google_firebase_web_app_config.app.storage_bucket
    VITE_FIREBASE_MESSAGING_SENDER_ID = data.google_firebase_web_app_config.app.messaging_sender_id
    VITE_FIRESTORE_DATABASE           = "(default)"
  }
}

output "web_env_admin_staging" {
  description = "VITE_* build vars for the admin staging web app (SP07, after launch)."
  value = var.admin_enabled ? {
    VITE_FIREBASE_API_KEY             = data.google_firebase_web_app_config.admin_staging[0].api_key
    VITE_FIREBASE_AUTH_DOMAIN         = data.google_firebase_web_app_config.admin_staging[0].auth_domain
    VITE_FIREBASE_PROJECT_ID          = var.project
    VITE_FIREBASE_APP_ID              = google_firebase_web_app.admin_staging[0].app_id
    VITE_FIREBASE_STORAGE_BUCKET      = data.google_firebase_web_app_config.admin_staging[0].storage_bucket
    VITE_FIREBASE_MESSAGING_SENDER_ID = data.google_firebase_web_app_config.admin_staging[0].messaging_sender_id
  } : null
}

output "web_env_admin_prod" {
  description = "VITE_* build vars for the admin prod web app (SP07, after launch)."
  value = var.admin_enabled ? {
    VITE_FIREBASE_API_KEY             = data.google_firebase_web_app_config.admin[0].api_key
    VITE_FIREBASE_AUTH_DOMAIN         = data.google_firebase_web_app_config.admin[0].auth_domain
    VITE_FIREBASE_PROJECT_ID          = var.project
    VITE_FIREBASE_APP_ID              = google_firebase_web_app.admin[0].app_id
    VITE_FIREBASE_STORAGE_BUCKET      = data.google_firebase_web_app_config.admin[0].storage_bucket
    VITE_FIREBASE_MESSAGING_SENDER_ID = data.google_firebase_web_app_config.admin[0].messaging_sender_id
  } : null
}
