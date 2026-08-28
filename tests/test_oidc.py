"""OIDC/JWKS 外部身份（§16 升级）：RS256 校验 签名 / iss / aud / exp / kid。"""

import base64
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from app.gateway.oidc import OidcTenantMapper, OidcVerifier
from app.main import create_app
from app.settings import Settings

ISS = "https://issuer.example"
AUD = "agent-platform"


def _b64_int(n: int) -> str:
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _rsa() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key, kid: str = "test-kid") -> dict:
    pub = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _b64_int(pub.n),
        "e": _b64_int(pub.e),
    }


def _sign(key, *, kid="test-kid", tenant_id="tenant-default", ttl_s=3600, iss=ISS, aud=AUD) -> str:
    now = int(time.time())
    payload = {
        "sub": "oidc-user",
        "tenant_id": tenant_id,
        "iss": iss,
        "aud": aud,
        "iat": now,
        "exp": now + ttl_s,
    }
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": kid})


def _jwks_transport(keys: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": keys})

    return httpx.MockTransport(handler)


def _oidc_settings(transport=None) -> tuple[OidcVerifier, Settings]:
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        llm_provider="mock",
        oidc_enabled=True,
        oidc_jwks_url=f"{ISS}/.well-known/jwks.json",
        oidc_issuer=ISS,
        oidc_audience=AUD,
    )
    return OidcVerifier(settings, transport=transport), settings


async def test_oidc_verify_valid_token():
    key = _rsa()
    verifier, _ = _oidc_settings(transport=_jwks_transport([_jwk(key)]))
    claims = await verifier.verify(_sign(key))
    assert claims["sub"] == "oidc-user"
    assert claims["tenant_id"] == "tenant-default"


async def test_oidc_verify_wrong_key_rejected():
    key = _rsa()
    other = _rsa()
    verifier, _ = _oidc_settings(transport=_jwks_transport([_jwk(key)]))
    with pytest.raises(jwt.PyJWTError):
        await verifier.verify(_sign(other))


async def test_oidc_verify_expired_rejected():
    key = _rsa()
    verifier, _ = _oidc_settings(transport=_jwks_transport([_jwk(key)]))
    with pytest.raises(jwt.ExpiredSignatureError):
        await verifier.verify(_sign(key, ttl_s=-10))


async def test_oidc_verify_wrong_issuer_rejected():
    key = _rsa()
    verifier, _ = _oidc_settings(transport=_jwks_transport([_jwk(key)]))
    with pytest.raises(jwt.InvalidIssuerError):
        await verifier.verify(_sign(key, iss="https://evil"))


async def test_oidc_verify_kid_not_in_jwks_rejected():
    key = _rsa()
    verifier, _ = _oidc_settings(transport=_jwks_transport([_jwk(key, kid="other-kid")]))
    with pytest.raises(jwt.PyJWTError):
        await verifier.verify(_sign(key, kid="missing-kid"))


def test_oidc_token_accepted_via_api():
    key = _rsa()
    verifier, settings = _oidc_settings(transport=_jwks_transport([_jwk(key)]))
    with TestClient(create_app()) as c:
        c.app.state.agent.oidc = verifier  # 注入测试 OIDC 校验器
        c.app.state.agent.oidc_tenant_mapper = OidcTenantMapper(settings)  # claim tenant_id → 租户
        token = _sign(key, tenant_id="tenant-default")
        r = c.post(
            "/tools/calc.add/execute",
            json={"args": {"a": 1, "b": 2}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["data"] == 3


def test_oidc_wrong_key_rejected_via_api():
    key = _rsa()
    verifier, _ = _oidc_settings(transport=_jwks_transport([_jwk(key)]))
    other = _rsa()
    with TestClient(create_app()) as c:
        c.app.state.agent.oidc = verifier
        r = c.post(
            "/tools/echo/execute",
            json={"args": {"text": "x"}},
            headers={"Authorization": f"Bearer {_sign(other)}"},
        )
        assert r.status_code == 401


# ---------- OIDC claim→tenant 映射（§16） ----------
def test_mapper_claim_value():
    settings = Settings(
        database_url="sqlite+aiosqlite://", llm_provider="mock", oidc_tenant_claim="custom:tenant"
    )
    mapper = OidcTenantMapper(settings)
    assert mapper.map({"custom:tenant": "tenant-a"}) == "tenant-a"


def test_mapper_email_domain():
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        llm_provider="mock",
        oidc_tenant_email_domains=json.dumps({"example.com": "tenant-a"}),
    )
    mapper = OidcTenantMapper(settings)
    assert mapper.map({"email": "u@example.com"}) == "tenant-a"


def test_mapper_default_fallback():
    settings = Settings(
        database_url="sqlite+aiosqlite://", llm_provider="mock", oidc_default_tenant="tenant-d"
    )
    mapper = OidcTenantMapper(settings)
    assert mapper.map({"email": "u@nowhere.com"}) == "tenant-d"


def test_oidc_no_tenant_mapping_rejected_via_api():
    key = _rsa()
    verifier, settings = _oidc_settings(transport=_jwks_transport([_jwk(key)]))
    mapper = OidcTenantMapper(
        Settings(database_url="sqlite+aiosqlite://", llm_provider="mock")
    )  # 无 claim/域名/默认
    with TestClient(create_app()) as c:
        c.app.state.agent.oidc = verifier
        c.app.state.agent.oidc_tenant_mapper = mapper
        token = _sign(key, tenant_id=None)  # 无 tenant_id claim，无映射
        r = c.post(
            "/tools/echo/execute",
            json={"args": {"text": "x"}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403  # AUTH_NO_TENANT
