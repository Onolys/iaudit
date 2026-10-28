# Calling the backend with curl

**Audience:** users.

Start the service from `eaudit/` (see [eaudit/README.md](../../eaudit/README.md)). To try it without a provider key, start the stub pipeline, which returns an empty valid audit:

```bash
IAUDIT_PIPELINE=stub uv run uvicorn eaudit.app:app --port 8000
```

Send the contract's worked example (from the repo root):

```bash
curl -s -X POST http://localhost:8000/v1/audit \
  -H 'content-type: application/json' \
  -d @docs/contracts/examples/request.json
```

Expected: HTTP 200 and `{"schema_version":"0.0.1","request_id":"example-001","status":"complete","warnings":[],"claims":[]}`. With the default `full` pipeline and a provider key, `claims` is filled in; a full reply also carries `run_info` (models and prompt hashes; the stub omits it). The shape of a full reply is [response.json](../contracts/examples/response.json).

An error case: an unsupported version.

```bash
curl -s -i -X POST http://localhost:8000/v1/audit \
  -H 'content-type: application/json' \
  -d '{"schema_version":"9.9.9"}'
```

Expected: HTTP 400 with `error.code` `invalid_request`. All status codes: [backend-api.md](../reference/backend-api.md#errors).
