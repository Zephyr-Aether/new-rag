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
