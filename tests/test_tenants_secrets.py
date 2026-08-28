"""Phase 1 租户 onboarding + 密钥加密持久化。"""

import uuid

from starlette.testclient import TestClient

from app.gateway.passwords import client_sha256
from app.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_create_tenant_and_login_as_admin():
    with _client() as c:
        tid = f"tenant-{uuid.uuid4().hex[:8]}"
        admin = f"admin-{uuid.uuid4().hex[:6]}"
        r = c.post(
            "/tenants",
            json={
                "tenant_id": tid,
                "name": "Acme",
                "admin_user_id": admin,
                "admin_password": client_sha256("admin-pass"),
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["tenant_id"] == tid

        # 新租户管理员可登录，首登强制改密
        r = c.post(
            "/auth/token", json={"tenant_id": tid, "user_id": admin, "password": client_sha256("admin-pass")}
        )
        assert r.status_code == 200
        assert r.json()["must_change_password"] is True
        tok = r.json()["access_token"]

        # 新租户管理员可在自己租户建用户
        uid = f"u-{uuid.uuid4().hex[:6]}"
        r = c.post(
            "/users",
            json={"user_id": uid, "password": client_sha256("pw")},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200

        # 租户已列出
        assert any(t["id"] == tid for t in c.get("/tenants").json()["tenants"])


def test_secrets_api_set_list_delete():
    with _client() as c:
        assert c.post("/secrets", json={"ref": "llm.key", "value": "sk-xxx"}).status_code == 200
        assert any(s["ref"] == "llm.key" for s in c.get("/secrets").json()["secrets"])
        assert c.delete("/secrets/llm.key").status_code == 200
        assert all(s["ref"] != "llm.key" for s in c.get("/secrets").json()["secrets"])


def test_secret_encryption_roundtrip():
    from app.security.secrets import SecretManager

    mgr = SecretManager(key_source="test-master-key")
    encrypted = mgr._encrypt("super-secret-value")
    assert encrypted != "super-secret-value"  # 非明文
    assert mgr._decrypt(encrypted) == "super-secret-value"  # 可逆


def test_upload_session_tenant_isolated():
    """跨租户 IDOR：别的租户不能读写他人的上传会话（§15.7）。"""
    with _client() as c:
        # 默认租户创建上传会话
        r = c.post("/knowledge/upload/init", json={"filename": "a.txt", "size": 3})
        assert r.status_code == 200, r.text
        upload_id = r.json()["upload_id"]

        # 建第二个租户 + 管理员
        tid = f"tenant-{uuid.uuid4().hex[:6]}"
        admin = f"a-{uuid.uuid4().hex[:4]}"
        c.post("/tenants", json={"tenant_id": tid, "name": "B", "admin_user_id": admin})
        tok = c.post(
            "/auth/token", json={"tenant_id": tid, "user_id": admin, "password": client_sha256("pw")}
        ).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}

        # 别的租户访问 A 的上传会话 → 404（不可见）
        r = c.get(f"/knowledge/upload/{upload_id}/status", headers=h)
        assert r.status_code == 404
