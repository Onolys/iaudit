"""Maps every PRD acceptance criterion (AC1-AC18) to the tests that prove it.

This file only checks that each mapped test exists (as a function defined in the named file, not
marked `live`) and that no AC is unmapped. The tests themselves run in the normal suite:
`uv run --package onolys-api pytest -q -m "not live"` is the proof they pass.
"""

import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).parent

# AC -> [(test file, test function), ...]
CHECKLIST: dict[int, list[tuple[str, str]]] = {
    1: [
        ("test_public_contract.py", "test_openapi_is_the_committed_file"),
        ("test_public_contract.py", "test_contract_files_committed_and_current"),
        ("test_openapi.py", "test_openapi_deterministic_and_has_contract_components"),
    ],
    2: [
        ("test_acceptance_flow.py", "test_complete_flow_over_http_both_rating_orders"),
        ("test_acceptance_flow.py", "test_list_shows_done_failed_and_inflight"),
        (
            "test_run.py",
            "test_second_run_makes_v2_keeps_v1_and_reuses_transcript_with_other_preset",
        ),
        ("test_sessions_integration.py", "test_list_shows_inflight_failed_and_done"),
    ],
    3: [
        ("test_isolation.py", "test_every_id_route_is_404_for_another_user"),
        ("test_isolation.py", "test_every_id_route_is_covered"),
        ("test_repo_uid_filter.py", "test_every_query_function_is_uid_scoped"),
        ("test_repo_contract.py", "test_two_user_cross_uid_reads_and_writes_are_not_found"),
    ],
    4: [
        ("test_auth.py", "test_bad_tokens_are_401"),
        ("test_auth.py", "test_revoked_key_is_401_over_http"),
        ("test_auth.py", "test_regenerate_invalidates_old_key"),
        ("test_auth.py", "test_key_format_and_hash"),
    ],
    5: [
        ("test_validate.py", "test_duration_bounds"),
        ("test_validate.py", "test_too_large_by_object_size"),
        ("test_validate.py", "test_bad_magic_bytes_unsupported_audio"),
        ("test_validate.py", "test_no_audio_stream_audio_unreadable"),
        ("test_validate.py", "test_short_recording_warning_only"),
        ("test_audio_upload.py", "test_alias_maps_to_canonical_required_headers"),
        (
            "test_audio_integration.py",
            "test_real_ffmpeg_transcode_to_16k_mono_flac_and_stt_gets_audioref",
        ),
    ],
    6: [
        ("test_worker.py", "test_transient_failure_succeeds_on_attempt_2"),
        ("test_worker.py", "test_two_failures_end_failed_no_third_attempt"),
        ("test_worker.py", "test_permanent_error_not_retried"),
        ("test_worker.py", "test_duplicate_delivery_one_result"),
        ("test_run.py", "test_retried_run_reruns_everything_and_yields_one_report"),
        ("test_transcribe.py", "test_redelivered_transcribe_resumes_and_never_resubmits"),
        ("test_transcribe.py", "test_polls_stop_at_the_time_limit"),
        ("test_transcribe.py", "test_bad_transcripts_fail_with_code"),
        ("test_transcribe.py", "test_three_speakers_reach_the_gate"),
    ],
    7: [
        ("test_caps.py", "test_21st_run_of_the_day_is_429_daily_cap_reached"),
        ("test_caps.py", "test_concurrent_reservations_never_exceed_the_cap"),
        ("test_caps.py", "test_refund_before_any_llm_call_frees_the_slot_and_the_count"),
        (
            "test_first_run.py",
            "test_cap_hit_leaves_awaiting_input_with_error_code_and_leaks_nothing",
        ),
        ("test_run.py", "test_cap_held_first_run_starts_with_post_runs"),
    ],
    8: [("test_delete.py", "test_full_flow_delete_leaves_nothing_anywhere")],
    9: [
        ("test_logging.py", "test_no_sentinel_in_logs_over_full_flow"),
        ("test_logging.py", "test_failed_step_writes_exactly_one_line_with_required_keys"),
    ],
    10: [
        ("test_errors.py", "test_error_body_validates"),
        ("test_sessions.py", "test_errors_validate_against_public_schema"),
        ("test_public_contract.py", "test_every_error_status_has_an_error_model"),
    ],
    11: [
        ("test_audio_upload.py", "test_complete_returns_202_enqueues_validate_and_sets_validating"),
        ("test_sessions.py", "test_create_returns_202_and_ids"),
        ("test_sessions.py", "test_status_doc_schema_has_no_text"),
        ("test_machine.py", "test_status_doc_has_only_the_contract_fields"),
        ("test_machine.py", "test_stage_weights_sum_and_never_decrease_in_any_order"),
        ("test_rating.py", "test_limits_at_boundary_ok"),
        ("test_rating.py", "test_openapi_has_rating_and_no_upload_or_parse"),
    ],
    12: [
        ("test_combined_integration.py", "test_combined_mode_serves_healthz"),
        ("test_quickstart.py", "test_quickstart_runs_end_to_end"),
        ("test_worker.py", "test_worker_rejects_missing_or_bad_oidc"),
        ("test_worker.py", "test_oidc_bypassed_only_in_local_test"),
        ("test_dev_script_and_image.py", "test_dev_script_checks_and_runs_combined_quickstart"),
        ("test_dev_script_and_image.py", "test_dockerfile_matches_the_cloud_run_contract"),
    ],
    13: [
        ("test_first_run.py", "test_race_all_orders_sequential_and_concurrent"),
        ("test_first_run.py", "test_race_over_http_all_orders_repeated"),
    ],
    14: [
        ("test_rating.py", "test_draft_stored_never_submits_or_starts_run"),
        ("test_rating.py", "test_each_final_is_new_revision_latest_wins"),
        ("test_rating.py", "test_rejected_in_deleting"),
        ("test_rating.py", "test_no_object_written_to_blob_store"),
        ("test_run.py", "test_rerun_uses_latest_final_rating_and_n_runs"),
    ],
    15: [
        ("test_run.py", "test_paudit_failure_fails_run_and_session_and_releases_without_refund"),
        ("test_run.py", "test_eaudit_failure_ships_report_with_warning"),
        ("test_run.py", "test_tips_failure_ships_report_with_warning"),
    ],
    16: [
        ("test_run.py", "test_full_stub_flow_reaches_report_ready_with_progress_table"),
        ("test_run.py", "test_report_over_500kb_is_served_unchanged_from_gcs"),
        (
            "test_run.py",
            "test_second_run_makes_v2_keeps_v1_and_reuses_transcript_with_other_preset",
        ),
    ],
    17: [
        ("test_public_contract.py", "test_openapi_and_docs_answer_200_without_auth"),
        ("test_public_contract.py", "test_docs_page_references_no_other_host"),
        ("test_public_contract.py", "test_forbidden_paths_absent_and_path_params_named"),
        ("test_public_contract.py", "test_quickstart_in_openapi_description"),
        ("test_quickstart.py", "test_quickstart_runs_end_to_end"),
    ],
    18: [
        ("test_first_run.py", "test_confirm_in_report_ready_changes_next_run_only_report_unchanged")
    ],
}


def _functions(path: Path) -> dict[str, ast.AST]:
    tree = ast.parse(path.read_text())
    return {
        n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _marks(node: ast.AST) -> str:
    return " ".join(ast.unparse(d) for d in getattr(node, "decorator_list", []))


def test_every_acceptance_criterion_is_mapped():
    assert sorted(CHECKLIST) == list(range(1, 19))
    assert all(CHECKLIST[ac] for ac in CHECKLIST)


@pytest.mark.parametrize(
    ("ac", "fname", "test"),
    [(ac, f, t) for ac, refs in CHECKLIST.items() for f, t in refs],
    ids=lambda v: str(v),
)
def test_mapped_test_exists_and_is_not_live(ac, fname, test):
    path = TESTS / fname
    assert path.is_file(), f"AC{ac}: {fname} missing"
    fns = _functions(path)
    assert test in fns, f"AC{ac}: {fname}::{test} not found"
    assert test.startswith("test_")
    module_marks = " ".join(
        ast.unparse(n)
        for n in ast.parse(path.read_text()).body
        if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "pytestmark"
    )
    assert "mark.live" not in _marks(fns[test]) + module_marks, f"AC{ac}: {test} is marked live"
