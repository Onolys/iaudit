"""Identity Platform ID-token verification (signature, aud, iss, expiry) via google-auth.

The cert fetcher is injectable so tests sign tokens with a local key (no network).
"""

import threading
import time
from collections.abc import Callable

from google.auth import jwt

CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
)
CERT_TTL_S = 3600
CLOCK_SKEW_S = 10

CertFetcher = Callable[[], dict[str, str]]


class InvalidToken(Exception):
    pass


class UpstreamUnavailable(Exception):
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
                    raise UpstreamUnavailable from None
                self._fetched_at = self._clock()
            return self._certs

    def verify(self, token: str) -> dict:
        """Return the verified claims or raise InvalidToken / UpstreamUnavailable."""
        try:
            header = jwt.decode_header(token)
            if header.get("alg") != "RS256":
                raise InvalidToken
            certs = self._get_certs()
            if header.get("kid") not in certs:  # key rotation: refresh once
                certs = self._get_certs(force=True)
            claims = jwt.decode(
                token,
                certs=certs,
                audience=self._project,
                clock_skew_in_seconds=CLOCK_SKEW_S,
            )
        except UpstreamUnavailable:
            raise
        except Exception:
            raise InvalidToken from None
        if claims.get("iss") != f"https://securetoken.google.com/{self._project}":
            raise InvalidToken
        return claims
