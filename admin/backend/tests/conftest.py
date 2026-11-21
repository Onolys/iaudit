import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt, jwt

PROJECT = "onolys-test"
KID = "k1"


class Keys:
    def __init__(self) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.signer = crypt.RSASigner.from_string(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            KID,
        )
        self.certs = {
            KID: key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        }

    def mint(self, **over) -> str:
        now = int(time.time())
        claims = {
            "iss": f"https://securetoken.google.com/{PROJECT}",
            "aud": PROJECT,
            "sub": "uid-1",
            "iat": now,
            "exp": now + 600,
            "email": "alice@example.com",
            "email_verified": True,
        }
        claims.update(over)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(self.signer, claims).decode()


@pytest.fixture(scope="session")
def keys() -> Keys:
    return Keys()
