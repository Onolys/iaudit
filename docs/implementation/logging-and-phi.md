# Logging and PHI

The backend handles interview text that may be sensitive. Code: `eaudit/src/eaudit/safe_log.py`.

**Audience:** maintainers and coding agents.

- **Allowlist.** `log_event` keeps only fields named in `ALLOWED_FIELDS`: ids, counts, durations, modes and class names. Any other field is dropped silently. A field whose name contains `text`, `body`, `transcript`, `excerpt` or `message` is blocked even if allowed. Add a field to the list when a stage needs to log a new count.
- **Values.** Numbers are written bare; everything else is a capped, escaped string, so a value cannot forge another field.
- **Exceptions.** Log the class name and a few frame locations, never the message, because a message can hold user data.
- **Errors in replies.** Error bodies carry fixed messages and a request id, never instance values.
- **Metrics.** The per-request collector holds no prompt or output text.
- **Test.** A sentinel word placed in a transcript must never appear in logs, metrics or the `Server-Timing` header (`eaudit/tests/latency/test_latency.py`, scenario S9).
