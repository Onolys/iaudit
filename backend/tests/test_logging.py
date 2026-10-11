import json
import logging

from fastapi.testclient import TestClient

from iaudit_backend.app import create_app
from iaudit_backend.config import Settings
from iaudit_backend.safe_log import log_event

SENTINEL = "ZZ-SENTINEL-PHI-ZZ"


def test_log_event_drops_text_like_and_unknown_fields(caplog):
    with caplog.at_level(logging.INFO, logger="iaudit"):
        log_event(
            "x",
            request_id="r1",
            turns=3,
            text=SENTINEL,
            body=SENTINEL,
            transcript=SENTINEL,
            excerpt=SENTINEL,
            message=SENTINEL,
            error_message=SENTINEL,
            surprise=SENTINEL,
        )
    assert "request_id=r1" in caplog.text and "turns=3" in caplog.text
    assert SENTINEL not in caplog.text


def test_one_info_line_per_request(caplog, example_request):
    app = create_app(Settings(pipeline="stub", llm_mode="stub"))
    with TestClient(app) as c, caplog.at_level(logging.INFO, logger="iaudit"):
        caplog.clear()
        assert c.post("/v1/audit", content=json.dumps(example_request)).status_code == 200
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("audit_request")]
    assert len(lines) == 1
    line = lines[0]
    for key in (
        "request_id=example-001",
        "audit_uuid=",
        "turns=",
        "sections=",
        "status=200",
        "total_ms=",
    ):
        assert key in line


class Boom:
    async def run(self, req, ctx):
        raise RuntimeError(f"failed on {SENTINEL}")


def test_sentinel_never_in_logs_or_errors(caplog, example_request):
    def with_sentinel(**changes):
        r = json.loads(json.dumps(example_request))
        r["transcript"][0]["text"] = SENTINEL
        r["assessment"][0]["text"] = SENTINEL
        r.update(changes)
        return r

    dup = with_sentinel()
    dup["transcript"][0]["id"] = SENTINEL
    dup["transcript"][1]["id"] = SENTINEL
    bad_schema = with_sentinel()
    bad_schema["transcript"][1]["speaker"] = 5
    bad_schema["transcript"][1]["extra" + SENTINEL] = SENTINEL
    payloads = [
        json.dumps(with_sentinel()).encode(),  # success (stub) path
        json.dumps(with_sentinel(schema_version=SENTINEL)).encode(),
        json.dumps(bad_schema).encode(),
        json.dumps(dup).encode(),
        (SENTINEL + "{not json").encode(),
        json.dumps([SENTINEL]).encode(),
    ]
    caplog.set_level(logging.DEBUG)
    texts = []
    with TestClient(create_app(Settings(pipeline="stub", llm_mode="stub"))) as c:
        for p in payloads:
            texts.append(c.post("/v1/audit", content=p).text)
    with TestClient(create_app(Settings(pipeline="stub", llm_mode="stub", max_turns=1))) as c:
        texts.append(c.post("/v1/audit", content=payloads[0]).text)
    with TestClient(
        create_app(Settings(pipeline="stub", llm_mode="stub"), pipeline=Boom()),
        raise_server_exceptions=False,
    ) as c:
        texts.append(c.post("/v1/audit", content=payloads[0]).text)
    assert len(texts) == 8
    assert SENTINEL not in caplog.text
    assert all(SENTINEL not in t for t in texts)


def test_lines_print_to_stderr_without_caplog(capsys, example_request):
    """Under uvicorn nothing else configures logging: the app must attach its own handler."""
    with TestClient(create_app(Settings(pipeline="stub", llm_mode="stub"))) as c:
        assert c.post("/v1/audit", content=json.dumps(example_request)).status_code == 200
    err = capsys.readouterr().err
    assert "startup config=" in err
    assert "audit_request" in err and "request_id=" in err


def test_setup_logging_is_idempotent():
    from iaudit_backend.safe_log import setup_logging

    setup_logging("INFO")
    setup_logging("INFO")
    handlers = [h for h in logging.getLogger("iaudit").handlers if getattr(h, "_iaudit", False)]
    assert len(handlers) == 1
