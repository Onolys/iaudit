"""Identity Platform ID-token verification with Google's public keys.

Checks signature (securetoken certs), expiry, `aud` = project, `iss`, a non-empty `sub`
and `email_verified`. Only `uid` is taken from the claims. The cert fetcher is injectable so
tests mint tokens with a local key and never touch the network.
"""

import threading
import time
from collections.abc import Callable
from typing import Protocol

from google.auth import jwt

from onolys_api.errors import ApiError

CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
)
CERT_TTL_S = 3600
CLOCK_SKEW_S = 10

CertFetcher = Callable[[], dict[str, str]]


class TokenVerifier(Protocol):
    def verify(self, token: str) -> str:
        """Return the uid or raise `InvalidToken`."""
        ...


class InvalidToken(Exception):
    pass


def fetch_google_certs() -> dict[str, str]:
    import requests

    resp = requests.get(CERTS_URL, timeout=5)
    resp.raise_for_status()
    return resp.json()


class IdTokenVerifier:
    def __init__(
        self,
        project: str,
        fetch_certs: CertFetcher = fetch_google_certs,
        ttl_s: float = CERT_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._project = project
        self._fetch = fetch_certs
        self._ttl = ttl_s
        self._clock = clock
        self._certs: dict[str, str] = {}
        self._fetched_at = float("-inf")
        self._lock = threading.Lock()

    def _get_certs(self, force: bool = False) -> dict[str, str]:
        with self._lock:
            if force or self._clock() - self._fetched_at > self._ttl:
                try:
                    self._certs = self._fetch()
                except Exception:
                    raise ApiError.of(
                        503, "upstream_unavailable", "Service temporarily unavailable."
                    ) from None
                self._fetched_at = self._clock()
            return self._certs

    def _decode(self, token: str, certs: dict[str, str]) -> dict:
        return jwt.decode(
            token,
            certs=certs,
            audience=self._project,
            clock_skew_in_seconds=CLOCK_SKEW_S,
        )

    def verify(self, token: str) -> str:
        try:
            header = jwt.decode_header(token)
            if header.get("alg") != "RS256":
                raise InvalidToken
            certs = self._get_certs()
            if header.get("kid") not in certs:  # key rotation: refresh once
                certs = self._get_certs(force=True)
            claims = self._decode(token, certs)
        except ApiError:
            raise
        except Exception:
            raise InvalidToken from None
        if claims.get("iss") != f"https://securetoken.google.com/{self._project}":
            raise InvalidToken
        if claims.get("email_verified") is not True:
            raise InvalidToken
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub or len(sub) > 128 or "/" in sub:
            raise InvalidToken
        return sub
