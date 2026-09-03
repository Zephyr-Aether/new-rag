"""RBAC API（§6.2）：/roles 增改查 + /policies/meta 下拉数据。"""

import asyncio
import uuid

from starlette.testclient import TestClient

from app.gateway.auth import create_access_token
from app.main import create_app
from app.settings import get_settings
from app.storage.db import create_all, create_engine_and_sessions
from app.storage.models import PolicyRow


def _grant_manage(tenant: str) -> None:
    """给一个临时租户授予 policy:manage（require_perm 依赖它）。"""

    async def go() -> None:
        eng, sessions = create_engine_and_sessions(get_settings().database_url)
        await create_all(eng)
        async with sessions() as s:
            s.add(
                PolicyRow(
                    id=f"pol-{uuid.uuid4().hex[:12]}",
                    tenant_id=tenant,
                    name="grant-manage",
                    effect="ALLOW",
                    action="policy:manage",
                    resource="*",
                )
            )
            await s.commit()
        await eng.dispose()

    asyncio.run(go())


def _make_client(tenant: str) -> TestClient:
    _grant_manage(tenant)
    token = create_access_token(get_settings(), tenant_id=tenant, user_id="u")
    client = TestClient(create_app())
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_policy_meta_returns_actions_and_resources():
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    with _make_client(tenant) as c:
        r = c.get("/policies/meta")
        assert r.status_code == 200
        actions = r.json()["actions"]
        assert any(a["action"] == "policy:manage" and a["name"] for a in actions)
        resources = r.json()["resources"]
        assert any(x["resource"] == "*" for x in resources)
        # 已用资源也会进下拉数据
        c.post("/policies", json={"action": "kb:ingest", "resource": "kb-42"})
        res = c.get("/policies/meta").json()["resources"]
        assert any(x["resource"] == "kb-42" for x in res)


def test_role_update_renames_and_describes():
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    with _make_client(tenant) as c:
        rid = c.post("/roles", json={"name": "ops"}).json()["id"]
        r = c.put(f"/roles/{rid}", json={"name": "ops-v2", "description": "renamed"})
        assert r.status_code == 200
        roles = c.get("/roles").json()["roles"]
        match = [x for x in roles if x["id"] == rid][0]
        assert (match["name"], match["description"]) == ("ops-v2", "renamed")


def test_role_update_blank_name_400_and_missing_404():
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    with _make_client(tenant) as c:
        rid = c.post("/roles", json={"name": "ops"}).json()["id"]
        assert c.put(f"/roles/{rid}", json={"name": "  "}).status_code == 400
        assert c.put("/roles/role-missing", json={"name": "x"}).status_code == 404


def test_role_templates_list_and_create():
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    with _make_client(tenant) as c:
        tpl = c.get("/roles/templates").json()["templates"]
        keys = {t["key"] for t in tpl}
        assert {"admin", "operator", "reviewer", "viewer"} <= keys
        assert all(t["name"] and t["description"] for t in tpl)

        # 从模板创建：建角色 + 策略集
        r = c.post("/roles/templates", json={"template": "operator"})
        assert r.status_code == 200
        body = r.json()
        assert body["created"] is True and body["name"] == "运维"
        rid = body["id"]
        policies = c.get("/policies").json()["policies"]
        role_pols = [p for p in policies if p.get("role_id") == rid]
        assert any(p["action"] == "kb:ingest" for p in role_pols)
        assert any(p["action"] == "release:ops" for p in role_pols)
        # 无 release:publish（operator 不该有发布权）
        assert not any(p["action"] == "release:publish" for p in role_pols)

        # 幂等：同名已存在则复用
        again = c.post("/roles/templates", json={"template": "operator"}).json()
        assert again["created"] is False and again["id"] == rid


def test_role_template_unknown_400():
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    with _make_client(tenant) as c:
        assert c.post("/roles/templates", json={"template": "nope"}).status_code == 400


def test_create_tenant_boots_admin_role_and_default_policies():
    """Phase 1 租户生命周期：新建租户自动配默认管理员角色 + 默认策略（onboarding 一次到位）。"""
    admin_tenant = f"t-{uuid.uuid4().hex[:8]}"
    with _make_client(admin_tenant) as c:
        tid = f"t-{uuid.uuid4().hex[:6]}"
        admin_uid = f"u-{uuid.uuid4().hex[:6]}"
        r = c.post(
            "/tenants",
            json={"tenant_id": tid, "name": "Onboard Co", "admin_user_id": admin_uid, "admin_password": "hashed"},
        )
        assert r.status_code == 200 and r.json()["ok"] is True

    # 用新租户管理员的 token 查询（新租户自带 policy:manage，能过 require_perm）
    token = create_access_token(get_settings(), tenant_id=tid, user_id=admin_uid)
    with TestClient(create_app()) as c2:
        c2.headers.update({"Authorization": f"Bearer {token}"})
        roles = c2.get("/roles").json()["roles"]
        assert any(x["name"] == "管理员" for x in roles)
        pols = c2.get("/policies").json()["policies"]
        assert any(p["action"] == "kb:ingest" and p["resource"] == "*" for p in pols)
        assert any(p["action"] == "release:publish" for p in pols)
