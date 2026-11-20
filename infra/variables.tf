variable "project" {
  type    = string
  default = "onolys"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "admin_enabled" {
  description = "Gates every admin (SP07) resource."
  type        = bool
  default     = false
}

variable "staging_alerts" {
  description = "Enable the failure alerts on staging (prod is always on)."
  type        = bool
  default     = false
}

variable "monthly_budget_usd" {
  type    = number
  default = 50
}

variable "llm_secrets" {
  description = "Map of env-var name to secret id for LLM provider keys."
  type        = map(string)
  default     = { ANTHROPIC_API_KEY = "anthropic-api-key" }
}

variable "stt_secrets" {
  description = "Map of env-var name to secret id for STT provider keys (empty: Google STT uses ADC)."
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
