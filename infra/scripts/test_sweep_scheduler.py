"""Static check: scheduler.tf calls the worker's sweep endpoint every 10 min with the tasks-invoker OIDC."""
import pathlib
import re

TF = pathlib.Path(__file__).parent.parent / "modules" / "environment" / "scheduler.tf"


def test_sweep_job_targets_worker_with_invoker_oidc():
    text = TF.read_text()
    assert 'resource "google_cloud_scheduler_job" "sweep_stale"' in text
    assert re.search(r'schedule\s*=\s*"\*/10 \* \* \* \*"', text)
    assert '"${local.worker_url}/tasks/sweep-stale"' in text
    assert re.search(r"service_account_email\s*=\s*google_service_account\.tasks_invoker\.email", text)
    assert re.search(r"audience\s*=\s*local\.worker_url", text)
    assert 'name             = "sweep-stale-${var.env}"' in text
