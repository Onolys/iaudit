# --- Stale-status sweeper (SP04): fails sessions whose task chain broke ---
# Every 10 minutes Cloud Scheduler calls the worker's POST /tasks/sweep-stale with an OIDC token of
# the same tasks-invoker SA Cloud Tasks uses (run.invoker on the worker is already granted by
# `worker_tasks_invoker`; the audience is the worker URL, which the endpoint verifies).
resource "google_cloud_scheduler_job" "sweep_stale" {
  project          = var.project
  region           = var.region
  name             = "sweep-stale-${var.env}"
  description      = "Fail sessions stuck in transcribing/validating (${var.env})"
  schedule         = "*/10 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "180s"

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "${local.worker_url}/tasks/sweep-stale"

    oidc_token {
      service_account_email = google_service_account.tasks_invoker.email
      audience              = local.worker_url
    }
  }

  depends_on = [google_cloud_run_v2_service_iam_member.worker_tasks_invoker]
}
