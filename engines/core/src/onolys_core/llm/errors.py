"""Typed LLM errors. Stages decide the degraded behaviour; the client never swallows."""


class LLMError(Exception):
    pass


class LLMTimeout(LLMError):
    """The per-call timeout elapsed."""


class LLMUnavailable(LLMError):
    """Provider down, rate limited after retry, or auth failure."""


class LLMRateLimited(LLMUnavailable):
    """HTTP 429/529. The client backs off and retries within the deadline; raised only when the
    deadline leaves no room. `retry_after` is the provider's hint in seconds, if any."""

    def __init__(self, message: str = "LLM rate limited", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMBadOutput(LLMError):
    """Output unparseable or schema-invalid after the retry."""


class FixtureMiss(LLMError):
    """No recorded fixture for this request (never falls back to the network)."""
