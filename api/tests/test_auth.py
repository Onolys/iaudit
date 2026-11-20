"""R1 / AC4: ID tokens, API keys, /v1/api-key, fake-auth guard. No network."""

import time

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt, jwt
from onolys_core.errors import ConfigError

from onolys_api.app import create_app
from onolys_api.auth.idtoken import IdTokenVerifier
from onolys_api.auth.keys import hash_secret, new_key, parse_key
from onolys_api.config import Settings
from onolys_api.repo.fake import FakeRepo

PROJECT = "onolys-test"
KID = "k1"


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return priv.decode(), pub.decode()


PRIV, PUB = _keypair()
OTHER_PRIV, _ = _keypair()


def mint(uid="u1", *, verified=True, aud=PROJECT, iss=None, exp_in=3600, priv=PRIV, kid=KID):
    now = int(time.time())
    claims = {
        "sub": uid,
        "aud": aud,
        "iss": iss or f"https://securetoken.google.com/{PROJECT}",
        "iat": now - 5,
        "exp": now + exp_in,
        "email_verified": verified,
    }
    return jwt.encode(crypt.RSASigner.from_string(priv, kid), claims, header={"kid": kid}).decode()


@pytest.fixture
def idp_settings():
    return Settings(env="staging", service_mode="api", auth_mode="idp", auth_project=PROJECT)


@pytest.fixture
def repo(blobs):
    return FakeRepo(blobs)


@pytest.fixture
async def idp_client(idp_settings, repo, blobs):
    verifier = IdTokenVerifier(PROJECT, fetch_certs=lambda: {KID: PUB})
    app = create_app(idp_settings, repo=repo, blobs=blobs, token_verifier=verifier)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        yield c


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def assert_401(r):
    assert r.status_code == 401
    assert r.json()["details"][0]["code"] == "unauthenticated"


# ---- ID tokens ----


async def test_valid_token_resolves_uid_and_creates_user(idp_client, repo):
    assert repo.get_user("u1") is None
    r = await idp_client.get("/v1/api-key", headers=bearer(mint("u1")))
    assert r.status_code == 200
    assert repo.get_user("u1") is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"exp_in": -3600},  # expired
        {"verified": False},  # email not verified
        {"aud": "other-project"},
        {"iss": "https://securetoken.google.com/other"},
        {"priv": OTHER_PRIV},  # bad signature
        {"kid": "unknown"},
    ],
)
async def test_bad_tokens_are_401(idp_client, kwargs):
    assert_401(await idp_client.get("/v1/api-key", headers=bearer(mint(**kwargs))))


async def test_garbage_and_missing_credentials_are_401(idp_client):
    assert_401(await idp_client.get("/v1/api-key", headers=bearer("not-a-jwt")))
    assert_401(await idp_client.get("/v1/api-key"))
    assert_401(await idp_client.get("/v1/api-key", headers=bearer("test:u1")))  # no fake in idp


async def test_cert_rotation_refetches_once():
    calls = []
    certs = {"old": "x"}

    def fetch():
        calls.append(1)
        return dict(certs)

    v = IdTokenVerifier(PROJECT, fetch_certs=fetch)
    assert v._get_certs() == {"old": "x"}
    certs.clear()
    certs[KID] = PUB
    assert v.verify(mint("u9")) == "u9"
    assert len(calls) == 2


async def test_cert_fetch_failure_is_503(repo, blobs, idp_settings):
    def boom():
        raise OSError("down")

    app = create_app(
        idp_settings, repo=repo, blobs=blobs, token_verifier=IdTokenVerifier(PROJECT, boom)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        r = await c.get("/v1/api-key", headers=bearer(mint()))
    assert r.status_code == 503


# ---- fake auth ----


async def test_fake_auth_accepts_test_uid(client):
    r = await client.get("/v1/api-key", headers=bearer("test:alice"))
    assert r.status_code == 200 and r.json() == {
        "active": False,
        "key_id": None,
        "created": None,
        "last_used_at": None,
    }


@pytest.mark.parametrize("tok", ["alice", "test:", "test:a/b", "other:alice"])
async def test_fake_auth_rejects_malformed(client, tok):
    assert_401(await client.get("/v1/api-key", headers=bearer(tok)))


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_fake_auth_refused_outside_local_test(env, blobs):
    s = Settings(env=env, service_mode="api", auth_mode="fake")  # bypasses from_env validation
    with pytest.raises(ConfigError):
        create_app(s, repo=FakeRepo(blobs), blobs=blobs)
    with pytest.raises(ConfigError):
        Settings.from_env({"ENV": env, "AUTH_MODE": "fake"})


def test_idp_requires_project(blobs):
    s = Settings(env="staging", service_mode="api", auth_mode="idp")
    with pytest.raises(ConfigError):
        create_app(s, repo=FakeRepo(blobs), blobs=blobs)


# ---- API keys ----


def test_key_format_and_hash():
    key_id, full, digest = new_key()
    parsed = parse_key(full)
    assert parsed is not None and parsed[0] == key_id
    assert digest == hash_secret(parsed[1]) and digest != parsed[1] and digest not in full
    assert parse_key("onolys_zz_short") is None


async def test_api_key_lifecycle(client, app):
    repo = app.state.repo
    h = bearer("test:alice")
    created = (await client.post("/v1/api-key", headers=h)).json()
    key = created["api_key"]
    assert key.startswith(f"onolys_{created['key_id']}_")
    secret = parse_key(key)[1]

    stored = repo.active_api_key("alice")
    assert stored.hash != secret and stored.hash == hash_secret(secret)
    assert secret not in repr(stored.to_store())

    info = (await client.get("/v1/api-key", headers=h)).json()
    assert info["active"] and info["key_id"] == created["key_id"] and "api_key" not in info

    # key authenticates as the same uid, and records last_used_at
    # (a key cannot reach /api-key, so use a second token user to prove uid mapping below)
    assert repo.get_api_key(created["key_id"]).last_used_at is None
    r = await client.get("/v1/api-key", headers={"X-API-Key": key})
    assert r.status_code == 403  # authenticated, but token-only route
    assert repo.get_api_key(created["key_id"]).last_used_at is not None


async def test_api_key_refused_on_key_management(client):
    key = (await client.post("/v1/api-key", headers=bearer("test:alice"))).json()["api_key"]
    for method in ("GET", "POST", "DELETE"):
        r = await client.request(method, "/v1/api-key", headers={"X-API-Key": key})
        assert r.status_code == 403
        assert r.json()["details"][0]["code"] == "forbidden"
    # and nothing was revoked or replaced
    assert (await client.get("/v1/api-key", headers=bearer("test:alice"))).json()["active"]


async def test_regenerate_invalidates_old_key(client, app):
    repo = app.state.repo
    h = bearer("test:alice")
    old = (await client.post("/v1/api-key", headers=h)).json()
    new = (await client.post("/v1/api-key", headers=h)).json()
    assert old["key_id"] != new["key_id"]
    auth = app.state.auth
    assert auth.authenticate(None, new["api_key"]).uid == "alice"
    from onolys_api.errors import ApiError

    with pytest.raises(ApiError) as e:
        auth.authenticate(None, old["api_key"])
    assert e.value.status == 401 and e.value.details[0]["code"] == "unauthenticated"
    assert repo.get_api_key(old["key_id"]).revoked_at is not None


async def test_revoked_key_is_401_over_http(client, app):
    h = bearer("test:alice")
    key = (await client.post("/v1/api-key", headers=h)).json()["api_key"]
    assert (await client.delete("/v1/api-key", headers=h)).status_code == 204
    assert (await client.delete("/v1/api-key", headers=h)).status_code == 204  # idempotent
    assert not (await client.get("/v1/api-key", headers=h)).json()["active"]
    r = await client.get("/v1/api-key", headers={"X-API-Key": key})
    assert_401(r)


@pytest.mark.parametrize(
    "bad",
    [
        "garbage",
        "onolys_0123456789abcdef_" + "A" * 43,  # unknown id
    ],
)
async def test_bad_or_unknown_key_is_401(client, bad):
    assert_401(await client.get("/v1/api-key", headers={"X-API-Key": bad}))


async def test_wrong_secret_is_401(client):
    created = (await client.post("/v1/api-key", headers=bearer("test:alice"))).json()
    forged = f"onolys_{created['key_id']}_" + "B" * 43
    assert_401(await client.get("/v1/api-key", headers={"X-API-Key": forged}))


async def test_key_maps_to_owner_uid(client, app):
    ka = (await client.post("/v1/api-key", headers=bearer("test:alice"))).json()["api_key"]
    kb = (await client.post("/v1/api-key", headers=bearer("test:bob"))).json()["api_key"]
    assert app.state.auth.authenticate(None, ka).uid == "alice"
    user = app.state.auth.authenticate(None, kb)
    assert (user.uid, user.auth_kind) == ("bob", "api_key")


async def test_healthz_needs_no_auth(client):
    assert (await client.get("/v1/healthz")).status_code == 200
