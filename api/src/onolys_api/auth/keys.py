"""API keys: `onolys_<id>_<secret>`. 256-bit secret, SHA-256 at rest, id-prefix lookup."""

import hashlib
import hmac
import re
import secrets

PREFIX = "onolys"
_KEY_RE = re.compile(r"^onolys_([0-9a-f]{16})_([A-Za-z0-9_-]{43})$")


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def new_key() -> tuple[str, str, str]:
    """Return (key_id, full_key, secret_hash). The full key is shown to the user once."""
    key_id = secrets.token_hex(8)
    secret = secrets.token_urlsafe(32)  # 32 random bytes -> 43 chars
    return key_id, f"{PREFIX}_{key_id}_{secret}", hash_secret(secret)


def parse_key(raw: str) -> tuple[str, str] | None:
    """Return (key_id, secret) or None when the string is not shaped like a key."""
    m = _KEY_RE.match(raw)
    return (m.group(1), m.group(2)) if m else None


def secret_matches(secret: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), stored_hash)
