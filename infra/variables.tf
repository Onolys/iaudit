variable "project" {
  type    = string
  default = "onolys"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "admin_enabled" {
  description = "Gates the admin (SP07) resources per environment: staging builds the staging admin backend, site, web app and authorised domain; prod stays off until launch."
  type        = map(bool)
  default = {
    staging = true
    prod    = false
  }

  validation {
    condition     = toset(keys(var.admin_enabled)) == toset(["staging", "prod"])
    error_message = "admin_enabled needs exactly the keys staging and prod."
  }
}

variable "staging_alerts" {
  description = "Enable the failure alerts on staging (prod is always on)."
  type        = bool
  default     = false
}

variable "monthly_budget_usd" {
  description = "Monthly budget in USD (alerts only, no spend cap)."
  type        = number
  default     = 20
}

variable "alert_email" {
  description = "Owner email for budget and failure alerts (Monitoring channel needs a verification click)."
  type        = string
  default     = "tejitpabari99@gmail.com"
}

variable "billing_account_id" {
  description = "Billing account linked to the project (from cloudbilling projects/onolys/billingInfo)."
  type        = string
  default     = "0175C5-F7E3DF-EE9F98"
}

variable "llm_secrets" {
  description = "Map of env-var name to base secret id for LLM provider keys; each environment gets `<base>-<env>`."
  type        = map(string)
  default     = { ANTHROPIC_API_KEY = "anthropic-api-key" }
}

variable "stt_secrets" {
  description = "Map of env-var name to base secret id for STT provider keys, per environment `<base>-<env>` (empty: Google STT uses ADC)."
  type        = map(string)
  default     = {}
}

variable "worker_concurrency" {
  type    = number
  default = 2
}

variable "worker_max_instances" {
  description = "Cloud Tasks max_concurrent_dispatches = worker_concurrency x worker_max_instances."
  type        = number
  default     = 3
}

# Hosting site ids are globally unique across Firebase. If one is taken, use the
# `onolys-miti-app*` fallbacks (PRD R11) and record which in docs/reference/infra.md.
variable "app_site_id" {
  type    = string
  default = "onolys-app"
}

variable "app_staging_site_id" {
  type    = string
  default = "onolys-app-staging"
}

variable "admin_site_id" {
  type    = string
  default = "onolys-admin"
}

variable "admin_staging_site_id" {
  type    = string
  default = "onolys-admin-staging"
}

variable "github_repository" {
  description = "GitHub repo (owner/name) allowed to impersonate the deployer SAs via WIF."
  type        = string
  default     = "Onolys/onolys"
}
