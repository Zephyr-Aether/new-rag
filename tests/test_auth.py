"""JWT 认证（§16/§27）：签发 / 校验 / 过期 / 篡改 / issuer。"""

from starlette.testclient import TestClient

from app.gateway.auth import create_access_token
from app.gateway.passwords import client_sha256
from app.main import create_app
from app.settings import Settings

DEFAULT_TENANT = "tenant-default"  # 种子租户（DEFAULT_POLICIES 放行 calc.add/echo）
SEED_USER = "user-default"  # 种子用户，密码 admin123（客户端先 SHA-256）
SEED_PWD = client_sha256("admin123")


def _settings(**kw) -> Settings:
    return Settings(database_url="sqlite+aiosqlite://", llm_provider="mock", **kw)


def test_mint_token_and_call_api():
    token = create_access_token(_settings(), tenant_id=DEFAULT_TENANT, user_id="u")
    with TestClient(create_app()) as c:
        r = c.post(
            "/tools/calc.add/execute",
            json={"args": {"a": 1, "b": 2}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["data"] == 3


def test_auth_token_endpoint_mints_usable_token():
    with TestClient(create_app()) as c:
        r = c.post(
            "/auth/token", json={"tenant_id": DEFAULT_TENANT, "user_id": SEED_USER, "password": SEED_PWD}
        )
        assert r.status_code == 200
        token = r.json()["access_token"]
        r2 = c.post(
            "/tools/echo/execute",
            json={"args": {"text": "hi"}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200


def test_token_rejected_for_unknown_user():
    with TestClient(create_app()) as c:
        r = c.post("/auth/token", json={"tenant_id": DEFAULT_TENANT, "user_id": "no-such-user"})
        assert r.status_code == 401
        assert r.json()["code"] == "AUTH_INVALID_CREDENTIALS"


def test_token_rejected_for_wrong_password():
    with TestClient(create_app()) as c:
        r = c.post(
            "/auth/token",
            json={"tenant_id": DEFAULT_TENANT, "user_id": SEED_USER, "password": client_sha256("wrong-pass")},
        )
        assert r.status_code == 401
        assert r.json()["code"] == "AUTH_INVALID_CREDENTIALS"


def test_expired_token_rejected():
    token = create_access_token(_settings(), tenant_id=DEFAULT_TENANT, user_id="u", expires_s=-1)
    with TestClient(create_app()) as c:
        r = c.post(
            "/tools/echo/execute",
            json={"args": {"text": "x"}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 401


def test_tampered_token_rejected():
    token = create_access_token(_settings(), tenant_id=DEFAULT_TENANT, user_id="u")
    tampered = token[:-4] + "abcd"
    with TestClient(create_app()) as c:
        r = c.post(
            "/tools/echo/execute",
            json={"args": {"text": "x"}},
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert r.status_code == 401


def test_wrong_issuer_rejected():
    token = create_access_token(_settings(auth_jwt_issuer="issuer-a"), tenant_id=DEFAULT_TENANT, user_id="u")
    with TestClient(create_app()) as c:  # 应用默认 issuer=agent-platform
        r = c.post(
            "/tools/echo/execute",
            json={"args": {"text": "x"}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 401
