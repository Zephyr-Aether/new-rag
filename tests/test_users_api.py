"""Phase 1 用户管理 API：CRUD / 禁用登录 / 改密 / 首次登录强制改密。"""

import uuid

from starlette.testclient import TestClient

from app.gateway.passwords import client_sha256
from app.main import create_app

TENANT = "tenant-default"


def _client() -> TestClient:
    return TestClient(create_app())


def _new_user(c: TestClient, pwd="pass-123", prefix="u") -> str:
    uid = f"{prefix}-{uuid.uuid4().hex[:8]}"
    r = c.post(
        "/users",
        json={
            "user_id": uid,
            "email": f"{uid}@local",
            "display_name": "测试用户",
            "password": client_sha256(pwd),
        },
    )
    assert r.status_code == 200, r.text
    return uid


def test_user_crud_and_list():
    with _client() as c:
        uid = _new_user(c)
        users = c.get("/users").json()["users"]
        match = [u for u in users if u["id"] == uid][0]
        assert match["enabled"] is True
        assert match["must_change_password"] is True  # 管理员配的密码需首次改

        r = c.put(f"/users/{uid}", json={"display_name": "改名", "enabled": False})
        assert r.status_code == 200
        match = [u for u in c.get("/users").json()["users"] if u["id"] == uid][0]
        assert match["display_name"] == "改名" and match["enabled"] is False

        assert c.delete(f"/users/{uid}").status_code == 200
        assert uid not in [u["id"] for u in c.get("/users").json()["users"]]


def test_disabled_user_cannot_login():
    with _client() as c:
        uid = _new_user(c)
        c.put(f"/users/{uid}", json={"enabled": False})
        r = c.post(
            "/auth/token", json={"tenant_id": TENANT, "user_id": uid, "password": client_sha256("pass-123")}
        )
        assert r.status_code == 403
        assert r.json()["code"] == "AUTH_DISABLED"


def test_first_login_requires_change_password():
    with _client() as c:
        uid = _new_user(c)
        r = c.post(
            "/auth/token", json={"tenant_id": TENANT, "user_id": uid, "password": client_sha256("pass-123")}
        )
        assert r.status_code == 200
        assert r.json()["must_change_password"] is True
        token = r.json()["access_token"]

        r = c.post(
            "/auth/password",
            json={"old_password": client_sha256("pass-123"), "new_password": client_sha256("new-pass")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

        r = c.post(
            "/auth/token", json={"tenant_id": TENANT, "user_id": uid, "password": client_sha256("new-pass")}
        )
        assert r.status_code == 200
        assert r.json()["must_change_password"] is False


def test_change_password_rejects_wrong_old():
    with _client() as c:
        uid = _new_user(c)
        token = c.post(
            "/auth/token", json={"tenant_id": TENANT, "user_id": uid, "password": client_sha256("pass-123")}
        ).json()["access_token"]
        r = c.post(
            "/auth/password",
            json={"old_password": client_sha256("wrong"), "new_password": client_sha256("x")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 401
