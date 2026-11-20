# syntax=docker/dockerfile:1
# Admin gateway image (SP07 R9): auth + CORS in front of eaudit, plus admin-only /v1/paudit.
# Build from the REPO ROOT:
#   docker build -f admin/backend/Dockerfile -t onolys-admin-backend .
#   docker run --rm -p 8080:8080 -e ADMIN_ALLOWED_EMAILS=you@example.com \
#     -e ADMIN_AUTH_PROJECT=<gcp-project> onolys-admin-backend
# Safe defaults: ENV=prod and ADMIN_AUTH=on (auth enforced, ADMIN_AUTH=off refused, an empty allowlist
# refuses to start). Local no-auth needs an explicit -e ENV=local -e ADMIN_AUTH=off.
# No real data baked in: only the MITI pack's synthetic fixtures ship (via protocols/); no eval code,
# datasets or transcripts (also see .dockerignore).

FROM python:3.12-slim-bookworm AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install --no-cache-dir uv==0.13.4
WORKDIR /src
# Dependency layer: manifests only (every workspace member's pyproject must exist for uv).
COPY pyproject.toml uv.lock ./
COPY engines/core/pyproject.toml engines/core/pyproject.toml
COPY engines/eaudit/pyproject.toml engines/eaudit/pyproject.toml
COPY engines/paudit/pyproject.toml engines/paudit/pyproject.toml
COPY engines/evaluation/pyproject.toml engines/evaluation/pyproject.toml
COPY api/pyproject.toml api/pyproject.toml
COPY admin/auth/pyproject.toml admin/auth/pyproject.toml
COPY admin/backend/pyproject.toml admin/backend/pyproject.toml
RUN uv sync --frozen --no-dev --package onolys-admin-backend --no-install-workspace
# Only the packages the gateway needs (paudit ships its JSON schemas inside the wheel).
COPY engines/core engines/core
COPY engines/eaudit engines/eaudit
COPY engines/paudit engines/paudit
COPY admin/auth admin/auth
COPY admin/backend admin/backend
RUN uv sync --frozen --no-dev --no-editable --package onolys-admin-backend

FROM python:3.12-slim-bookworm
RUN useradd --system --uid 10001 --create-home onolys
COPY --from=build /opt/venv /opt/venv
COPY protocols /app/protocols
# eaudit validates requests/responses against these schemas at startup (IAUDIT_CONTRACTS_DIR).
COPY docs/contracts/*.schema.json /app/contracts/
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PORT=8080 ENV=prod ADMIN_AUTH=on \
    PAUDIT_PROTOCOLS_DIR=/app/protocols IAUDIT_CONTRACTS_DIR=/app/contracts
WORKDIR /app
USER onolys
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn --factory onolys_admin_backend.app:create_app --host 0.0.0.0 --port ${PORT} --no-access-log --proxy-headers --forwarded-allow-ips='*'"]
