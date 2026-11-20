variable "project" {
  type = string
}

variable "region" {
  type = string
}

variable "env" {
  description = "Environment name: staging or prod."
  type        = string
  validation {
    condition     = contains(["staging", "prod"], var.env)
    error_message = "env must be staging or prod."
  }
}

variable "database_id" {
  description = "Firestore database id: `staging` for staging, `(default)` for prod."
  type        = string
}

variable "delete_protection" {
  description = "Firestore delete protection (on for prod)."
  type        = bool
  default     = false
}

variable "cors_origins" {
  description = "Browser origins allowed to PUT to the audio bucket via signed URLs."
  type        = list(string)
}

variable "worker_concurrency" {
  type = number
}

variable "worker_max_instances" {
  description = "Queue max_concurrent_dispatches = worker_concurrency x worker_max_instances."
  type        = number
}

variable "llm_secrets" {
  description = "Env-var name to secret id (shell created by the caller) for LLM provider keys."
  type        = map(string)
}

variable "stt_secrets" {
  description = "Env-var name to secret id for STT provider keys (worker only)."
  type        = map(string)
  default     = {}
}

variable "admin_enabled" {
  description = "Gates every admin-backend (SP07) resource."
  type        = bool
  default     = false
}

variable "admin_cors_origins" {
  description = "Browser origins the admin-backend answers CORS preflight for."
  type        = list(string)
  default     = []
}

variable "placeholder_image" {
  description = "Public image used until CI deploys the real one (image is ignored after create)."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "api_max_instances" {
  type    = number
  default = 3
}

variable "admin_max_instances" {
  type    = number
  default = 3
}

variable "daily_run_cap" {
  type    = number
  default = 20
}

variable "default_preset" {
  description = "Default preset name in the routes file (SP01)."
  type        = string
  default     = "default"
}

variable "git_sha" {
  description = "Initial GIT_SHA env value; CI overwrites it at deploy (PRD R13/R14)."
  type        = string
  default     = "unset"
}

variable "alerts_enabled" {
  description = "Create the failure alert policies (prod true; staging via staging_alerts)."
  type        = bool
  default     = false
}

variable "notification_channel_ids" {
  description = "Monitoring notification channel ids for the failure alerts."
  type        = list(string)
  default     = []
}
