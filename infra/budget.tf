# Owner notification channel (R15/R16): needs a one-time verification click in the owner's mailbox.
resource "google_monitoring_notification_channel" "owner_email" {
  project      = var.project
  display_name = "Onolys owner email"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.api]
}

data "google_project" "this" {
  project_id = var.project
}

# Budget (R15): alerts only, does not stop spend.
resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account_id
  display_name    = "onolys monthly"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.owner_email.id]
    disable_default_iam_recipients   = true
  }

  depends_on = [google_project_service.api]
}
