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
