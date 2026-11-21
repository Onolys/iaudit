# Cloud Run shells (PRD R8/R14). The image is owned by CI after first create (ignore_changes).
# GIT_SHA: provider v6 models `env` as a SET, so a single entry cannot be ignored (env[0] is rejected)
# and ignoring all of env would also hide secret-ref changes. GIT_SHA is therefore a variable;
# after a CI deploy, plan shows it as drift until applied with -var git_sha=<deployed sha>.

locals {
  worker_url = "https://onolys-worker-${var.env}-${data.google_project.this.number}.${var.region}.run.app"
  routes_env = [
    { name = "ROUTES_FILE", value = "config/${var.env}/routes.yaml" },
    { name = "DEFAULT_PRESET", value = var.default_preset },
  ]
  platform_env = [
    { name = "ENV", value = var.env },
    { name = "GCP_PROJECT", value = var.project },
    { name = "REGION", value = var.region },
    { name = "FIRESTORE_DATABASE", value = var.database_id },
    { name = "AUTH_PROJECT", value = var.project },
    { name = "AUDIO_BUCKET", value = google_storage_bucket.audio.name },
    { name = "DAILY_RUN_CAP", value = tostring(var.daily_run_cap) },
    { name = "ADAPTERS", value = "real" },
    { name = "TASKS_QUEUE", value = google_cloud_tasks_queue.steps.name },
    { name = "TASKS_SA", value = google_service_account.tasks_invoker.email },
    { name = "WORKER_URL", value = local.worker_url },
  ]
}

resource "google_cloud_run_v2_service" "api" {
  project             = var.project
  location            = var.region
  name                = "onolys-api-${var.env}"
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.api.email
    timeout                          = "60s"
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = 0
      max_instance_count = var.api_max_instances
    }

    containers {
      image = var.placeholder_image

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle = true
      }

      env {
        name  = "GIT_SHA"
        value = var.git_sha
      }
      env {
        name  = "SERVICE_MODE"
        value = "api"
      }
      env {
        # V4 signed URLs on Cloud Run have no private key: GcsBlobStore signs through IAM signBlob as this SA
        # (api_self_token_creator grants it). Without it the upload-URL call fails with a 500.
        name  = "BLOB_SIGNER_EMAIL"
        value = google_service_account.api.email
      }
      env {
        name = "UID_HMAC_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.uid_hmac.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "CORS_ORIGINS"
        value = join(",", var.cors_origins)
      }
      dynamic "env" {
        for_each = local.platform_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
      dynamic "env" {
        for_each = local.routes_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].revision,
      client,
      scaling, # service-level block the API fills with zeros (perpetual diff); per-revision scaling is set in template
      client_version,
    ]
  }

  depends_on = [google_secret_manager_secret_iam_member.hmac]
}

resource "google_cloud_run_v2_service" "worker" {
  project             = var.project
  location            = var.region
  name                = "onolys-worker-${var.env}"
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.worker.email
    timeout                          = "900s"
    max_instance_request_concurrency = var.worker_concurrency

    scaling {
      min_instance_count = 0
      max_instance_count = var.worker_max_instances
    }

    containers {
      image = var.placeholder_image

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
        cpu_idle = true
      }

      env {
        name  = "GIT_SHA"
        value = var.git_sha
      }
      env {
        name  = "SERVICE_MODE"
        value = "worker"
      }
      env {
        name = "UID_HMAC_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.uid_hmac.secret_id
            version = "latest"
          }
        }
      }
      dynamic "env" {
        for_each = local.platform_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
      dynamic "env" {
        for_each = local.routes_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
      dynamic "env" {
        for_each = local.worker_provider_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.provider[env.key].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].revision,
      client,
      scaling, # service-level block the API fills with zeros (perpetual diff); per-revision scaling is set in template
      client_version,
    ]
  }

  depends_on = [
    google_secret_manager_secret_iam_member.hmac,
    google_secret_manager_secret_iam_member.worker_provider,
  ]
}

resource "google_cloud_run_v2_service" "admin_backend" {
  count               = var.admin_enabled ? 1 : 0
  project             = var.project
  location            = var.region
  name                = "onolys-admin-backend-${var.env}"
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.admin_backend[0].email
    timeout                          = "130s"
    max_instance_request_concurrency = 20

    scaling {
      min_instance_count = 0
      max_instance_count = var.admin_max_instances
    }

    containers {
      image = var.placeholder_image

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle = true
      }

      env {
        name  = "GIT_SHA"
        value = var.git_sha
      }
      env {
        name  = "ENV"
        value = var.env
      }
      env {
        name  = "ADMIN_AUTH"
        value = "on"
      }
      env {
        name  = "ADMIN_AUTH_PROJECT"
        value = var.project
      }
      env {
        name  = "ADMIN_CORS_ORIGINS"
        value = join(",", var.admin_cors_origins)
      }
      dynamic "env" {
        for_each = local.routes_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
      env {
        name = "ADMIN_ALLOWED_EMAILS"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.admin_allowed_emails[0].secret_id
            version = "latest"
          }
        }
      }
      dynamic "env" {
        for_each = var.llm_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.provider[env.key].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].revision,
      client,
      scaling, # service-level block the API fills with zeros (perpetual diff); per-revision scaling is set in template
      client_version,
    ]
  }

  depends_on = [
    google_secret_manager_secret_iam_member.admin_llm,
    google_secret_manager_secret_iam_member.admin_emails,
  ]
}

# --- invokers (PRD R8) ---
resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "worker_tasks_invoker" {
  project  = var.project
  location = var.region
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.tasks_invoker.email}"
}

resource "google_cloud_run_v2_service_iam_member" "admin_public" {
  count    = var.admin_enabled ? 1 : 0
  project  = var.project
  location = var.region
  name     = google_cloud_run_v2_service.admin_backend[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
