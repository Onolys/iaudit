output "database_id" {
  value = google_firestore_database.db.name
}

output "bucket_name" {
  value = google_storage_bucket.audio.name
}

output "queue_name" {
  value = google_cloud_tasks_queue.steps.name
}

output "queue_id" {
  value = google_cloud_tasks_queue.steps.id
}

output "api_sa_email" {
  value = google_service_account.api.email
}

output "worker_sa_email" {
  value = google_service_account.worker.email
}

output "tasks_invoker_sa_email" {
  value = google_service_account.tasks_invoker.email
}

output "stt_service_agent_email" {
  value = google_project_service_identity.speech.email
}

output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "worker_url" {
  value = google_cloud_run_v2_service.worker.uri
}
