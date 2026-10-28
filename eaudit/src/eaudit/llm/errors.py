"""Typed LLM errors. Stages decide the degraded behaviour; the client never swallows."""


class LLMError(Exception):
    pass


class LLMTimeout(LLMError):
    """The per-call timeout elapsed."""


class LLMUnavailable(LLMError):
    """Provider down, rate limited after retry, or auth failure."""


class LLMBadOutput(LLMError):
    """Output unparseable or schema-invalid after the retry."""


class FixtureMiss(LLMError):
    """No recorded fixture for this request (never falls back to the network)."""
