"""Google-signed OIDC tokens from Cloud Tasks to the worker (R5).

Same cert cache and RS256 checks as `IdTokenVerifier`; the differences are the issuer, the
audience (the worker URL) and the identity: the token's verified email must be the
tasks-invoker service account. The cert fetcher is injectable so tests never touch the network.
"""

from google.auth import jwt

from onolys_api.auth.idtoken import CLOCK_SKEW_S, CertFetcher, IdTokenVerifier, InvalidToken
from onolys_api.errors import ApiError

OIDC_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


def fetch_oidc_certs() -> dict[str, str]:
    import requests

    resp = requests.get(OIDC_CERTS_URL, timeout=5)
    resp.raise_for_status()
    return resp.json()


class OidcVerifier(IdTokenVerifier):
    def __init__(
        self,
        audience: str,
        invoker_email: str,
        fetch_certs: CertFetcher = fetch_oidc_certs,
        **kw,
    ) -> None:
        if not audience or not invoker_email:
            raise ValueError("audience and invoker_email are required")
        super().__init__("", fetch_certs=fetch_certs, **kw)
        self._audience = audience
        self._email = invoker_email

    def _decode(self, token: str, certs: dict[str, str]) -> dict:
        return jwt.decode(
            token, certs=certs, audience=self._audience, clock_skew_in_seconds=CLOCK_SKEW_S
        )

    def verify(self, token: str) -> str:
        """Return the invoker email or raise `InvalidToken`."""
        try:
            header = jwt.decode_header(token)
            if header.get("alg") != "RS256":
                raise InvalidToken
            certs = self._get_certs()
            if header.get("kid") not in certs:
                certs = self._get_certs(force=True)
            claims = self._decode(token, certs)
        except (InvalidToken, ApiError):
            raise
        except Exception:
            raise InvalidToken from None
        if claims.get("iss") not in ISSUERS:
            raise InvalidToken
        if claims.get("email_verified") is not True or claims.get("email") != self._email:
            raise InvalidToken
        return self._email
