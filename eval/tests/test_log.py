import logging

from iaudit_eval.log import log_event

SENTINEL = "ZZ-SENTINEL-PHI-ZZ"


def test_log_event_drops_text_like_and_unknown_fields(caplog):
    with caplog.at_level(logging.INFO, logger="iaudit_eval"):
        log_event(
            "x",
            run_id="r1",
            item_id="i1",
            http_status=200,
            text=SENTINEL,
            body=SENTINEL,
            transcript=SENTINEL,
            excerpt=SENTINEL,
            message=SENTINEL,
            error_message=SENTINEL,
            response_text=SENTINEL,
            surprise=SENTINEL,
        )
    assert 'run_id="r1"' in caplog.text and "http_status=200" in caplog.text
    assert SENTINEL not in caplog.text


def test_values_are_escaped(caplog):
    with caplog.at_level(logging.INFO, logger="iaudit_eval"):
        log_event("x", run_id='a"\nforged=1')
    assert "\n" not in caplog.records[0].getMessage()
