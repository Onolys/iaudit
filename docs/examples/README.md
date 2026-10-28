# Examples

Runnable public-API usage examples.

**Audience:** users.

- [mock/](mock/): fictional request/response pairs for audit contract 0.0.1, plus a validator, for UI work. Responses carry an optional `run_info` block; one omits it.
- [real/](real/): 10 real (role-played) PriMock57 consultations with evaluator-derived answer keys, for testing the auditor.
- [../contracts/examples/](../contracts/examples/): the single worked example that belongs to the contract itself.

- [curl.md](curl.md): call the backend with curl, including an error case.
- [python_client.py](python_client.py): a standard-library client that prints a verdict per claim.

`IAUDIT_PIPELINE=stub` returns an empty valid audit without a key; real output needs provider keys.
