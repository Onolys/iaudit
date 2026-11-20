# Failure alerts (PRD R16, D16): two per env, to the owner's email channel.
# Metric always exists; the policies are gated by var.alerts_enabled (prod on, staging behind var.staging_alerts).

resource "google_logging_metric" "api_5xx" {
  project = var.project
  name    = "onolys-api-5xx-${var.env}"
  filter  = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="onolys-api-${var.env}"
    httpRequest.status>=500
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_monitoring_alert_policy" "failed" {
  count        = var.alerts_enabled ? 1 : 0
  project      = var.project
  display_name = "Onolys failed step/run (${var.env})"
  combiner     = "OR"

  conditions {
    display_name = "status=failed log line"
    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_run_revision"
        resource.labels.service_name=("onolys-api-${var.env}" OR "onolys-worker-${var.env}")
        jsonPayload.status="failed"
      EOT
    }
  }

  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }

  notification_channels = var.notification_channel_ids
}

resource "google_monitoring_alert_policy" "api_5xx" {
  count        = var.alerts_enabled ? 1 : 0
  project      = var.project
  display_name = "Onolys api 5xx rate (${var.env})"
  combiner     = "OR"

  conditions {
    display_name = "more than 5 api 5xx in 5 min"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.api_5xx.name}\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = var.notification_channel_ids
}
