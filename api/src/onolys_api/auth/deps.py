"""`current_user` dependency: Bearer ID token or X-API-Key -> (uid, auth_kind)."""

import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from onolys_core.errors import ConfigError

from onolys_api.auth.idtoken import IdTokenVerifier, InvalidToken, TokenVerifier
from onolys_api.auth.keys import parse_key, secret_matches
from onolys_api.config import LOCAL_ENVS, Settings
from onolys_api.errors import ApiError
from onolys_api.repo.base import Repo

AuthKind = Literal["token", "api_key"]
FAKE_PREFIX = "test:"
_UID_OK = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
LAST_USED_EVERY = timedelta(minutes=1)  # throttle writes to the key doc
_SEEN_CAP = 10_000

_bearer = HTTPBearer(auto_error=False, description="Identity Platform ID token")
_api_key = APIKeyHeader(
    name="X-API-Key", auto_error=False, description="`onolys_<id>_<secret>` (see /v1/api-key)"
)


def _unauthenticated() -> ApiError:
    return ApiError.of(401, "unauthenticated", "Authentication required.")


@dataclass(frozen=True)
class AuthUser:
    uid: str
    auth_kind: AuthKind


class Authenticator:
    def __init__(
        self, settings: Settings, repo: Repo, verifier: TokenVerifier | None = None
    ) -> None:
        self._repo = repo
        self._fake = settings.auth_mode == "fake"
        if self._fake and settings.env not in LOCAL_ENVS:
            raise ConfigError("AUTH_MODE=fake is only allowed when ENV is local or test")
        self._verifier: TokenVerifier | None = None
        if not self._fake:
            project = settings.auth_project or settings.gcp_project
            if verifier is None and not project:
                raise ConfigError("AUTH_PROJECT (or GCP_PROJECT) is required when AUTH_MODE=idp")
            self._verifier = verifier or IdTokenVerifier(project)
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def _ensure_user(self, uid: str) -> None:
        if uid in self._seen:
            return
        self._repo.ensure_user(uid)
        with self._lock:
            if len(self._seen) >= _SEEN_CAP:
                self._seen.clear()
            self._seen.add(uid)

    def _from_bearer(self, token: str) -> AuthUser:
        if self._fake:
            uid = token.removeprefix(FAKE_PREFIX) if token.startswith(FAKE_PREFIX) else ""
            if not _UID_OK.match(uid):
                raise _unauthenticated()
            return AuthUser(uid, "token")
        assert self._verifier is not None
        try:
            return AuthUser(self._verifier.verify(token), "token")
        except InvalidToken:
            raise _unauthenticated() from None

    def _from_api_key(self, raw: str) -> AuthUser:
        parsed = parse_key(raw)
        if parsed is None:
            raise _unauthenticated()
        key_id, secret = parsed
        doc = self._repo.get_api_key(key_id)
        # always compare, so unknown ids and wrong secrets take the same path
        stored = doc.hash if doc is not None else "0" * 64
        ok = secret_matches(secret, stored)
        if doc is None or not ok or doc.revoked_at is not None:
            raise _unauthenticated()
        now = datetime.now(UTC)
        if doc.last_used_at is None or now - doc.last_used_at >= LAST_USED_EVERY:
            self._repo.mark_api_key_used(doc.uid, key_id, now)
        return AuthUser(doc.uid, "api_key")

    def authenticate(self, bearer: str | None, api_key: str | None) -> AuthUser:
        if bearer:
            user = self._from_bearer(bearer)
        elif api_key:
            user = self._from_api_key(api_key)
        else:
            raise _unauthenticated()
        self._ensure_user(user.uid)
        return user


def current_user(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    api_key: Annotated[str | None, Depends(_api_key)] = None,
) -> AuthUser:
    """Sync on purpose: the Repo is sync, so this runs in the threadpool."""
    auth: Authenticator = request.app.state.auth
    user = auth.authenticate(creds.credentials if creds else None, api_key)
    request.state.auth_kind = user.auth_kind
    return user


def current_user_token_only(user: Annotated[AuthUser, Depends(current_user)]) -> AuthUser:
    """API keys may not manage API keys or delete the account (R1)."""
    if user.auth_kind != "token":
        raise ApiError.of(403, "forbidden", "Not allowed.")
    return user
