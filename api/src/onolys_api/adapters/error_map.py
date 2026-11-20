"""One place that turns any engine exception into one public error code (SP09 R3, D2, D3).

`to_public(exc, attempt=1, stage="run") -> (code, retryable)`. Codes are existing public codes
(`onolys_api.errors.ERROR_CODES`); the user-facing text is `PUBLIC_MESSAGES[code]`, fixed text,
never the exception message. Classes the API does not depend on (paudit, eaudit) are matched by
module + class name or by the `code` attribute they inherit from `OnolysError`.
`stage="stt"` is the transcription path, where a transient provider error is
`upstream_unavailable` on attempt 1 and `transcription_failed` afterwards.
"""

from typing import Literal

from google.api_core import exceptions as gexc
from onolys_core.errors import InputError, OnolysError, PackError
from onolys_core.llm.errors import LLMError
from onolys_core.stt.google_chirp import SttProviderError

Stage = Literal["run", "stt"]

UPSTREAM = "upstream_unavailable"
DEADLINE = "deadline_exceeded"
TRANSCRIPTION = "transcription_failed"
INTERNAL = "internal_error"

PUBLIC_MESSAGES = {
    "invalid_parameters": "The request could not be run with this input.",
    UPSTREAM: "A service we depend on is unavailable. Run again shortly.",
    DEADLINE: "The run took too long. Run again.",
    TRANSCRIPTION: "The recording could not be transcribed. Upload a different file.",
    "no_speech": "No usable speech was found in the recording.",
    "speakers_not_separated": "The speakers could not be told apart in the recording.",
    "rate_limited": "Too many requests. Try again shortly.",
    INTERNAL: "Something went wrong on our side. Run again.",
}

# AdapterError codes that already are public codes: code -> retryable (SP04 R5)
_ADAPTER_CODES = {
    UPSTREAM: True,
    DEADLINE: True,
    "rate_limited": True,
    TRANSCRIPTION: False,
    "no_speech": False,
    "speakers_not_separated": False,
}

_GOOGLE_TRANSIENT = (
    gexc.TooManyRequests,
    gexc.ServiceUnavailable,
    gexc.InternalServerError,
    gexc.GatewayTimeout,
    gexc.DeadlineExceeded,
    gexc.Aborted,
    gexc.RetryError,
)


def _named(exc: BaseException, module: str, name: str) -> bool:
    return any(c.__name__ == name and c.__module__.startswith(module) for c in type(exc).__mro__)


def _stt_transient(exc: BaseException) -> bool:
    return bool(getattr(exc, "transient", False)) or isinstance(exc, _GOOGLE_TRANSIENT)


def to_public(exc: BaseException, attempt: int = 1, stage: Stage = "run") -> tuple[str, bool]:
    """Public error code and whether another attempt may help (the caller applies the attempt
    limit). `attempt` is 1-based."""
    code, retryable = _classify(exc, stage)
    if stage == "stt" and code == UPSTREAM and attempt >= 2:
        return TRANSCRIPTION, False  # a second transient failure: ask for a different file
    return code, retryable


def _classify(exc: BaseException, stage: Stage) -> tuple[str, bool]:
    # AdapterError lives in adapters.base (imports onolys_core only); import lazily: no cycle
    from onolys_api.adapters.base import AdapterError

    if isinstance(exc, AdapterError):
        if exc.code in _ADAPTER_CODES:
            return exc.code, _ADAPTER_CODES[exc.code]
        return INTERNAL, False
    if isinstance(exc, InputError):
        return "invalid_parameters", False
    if isinstance(exc, PackError):
        return INTERNAL, False
    if stage == "stt":
        if isinstance(exc, SttProviderError):
            return (UPSTREAM, True) if _stt_transient(exc) else (TRANSCRIPTION, False)
        if _stt_transient(exc):
            return UPSTREAM, True
    if isinstance(exc, LLMError):
        # unavailable, timeout, rate limited, bad output (D3): all retryable; FixtureMiss is a
        # test-only miss and never a provider outage
        if type(exc).__name__ == "FixtureMiss":
            return INTERNAL, False
        return UPSTREAM, True
    if isinstance(exc, TimeoutError) or _named(exc, "eaudit", "DeadlineExceeded"):
        return DEADLINE, True
    if isinstance(exc, OnolysError):
        # paudit CodePassFailed / GlobalsPassFailed / AllRunsFailed (`code = "run_failed"`): the
        # engine already halved/retried; R3 "anything else": not retried, owner alerted
        return INTERNAL, False
    return INTERNAL, False
