"""PolicyEngine：默认拒绝 / allow 命中 / DENY 优先（§6.2 / §6.8）。"""

import uuid

from app.common.contracts import Subject
from app.security.policy import PolicyEngine
from app.storage.models import PolicyRow


async def _add(sessions, tenant: str, action: str, resource: str, effect: str = "ALLOW") -> None:
    async with sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:8]}",
                tenant_id=tenant,
                name="x",
                effect=effect,
                action=action,
                resource=resource,
            )
        )
        await s.commit()


async def test_default_deny_when_no_policy(sessions):
    pe = PolicyEngine(sessions)
    d = await pe.is_allowed(Subject(tenant_id="no-policy", user_id="u"), "tool:execute", "calc.add")
    assert not d.allowed
    assert "default-deny" in d.reason


async def test_allow_match(sessions):
    await _add(sessions, "t2", "tool:execute", "calc.add")
    pe = PolicyEngine(sessions)
    d = await pe.is_allowed(Subject(tenant_id="t2", user_id="u"), "tool:execute", "calc.add")
    assert d.allowed
    assert d.policy_id is not None


async def test_deny_overrides_allow(sessions):
    await _add(sessions, "t3", "tool:execute", "calc.add", "ALLOW")
    await _add(sessions, "t3", "tool:execute", "calc.add", "DENY")
    pe = PolicyEngine(sessions)
    d = await pe.is_allowed(Subject(tenant_id="t3", user_id="u"), "tool:execute", "calc.add")
    assert not d.allowed
    assert "deny" in d.reason


async def test_wildcard_allow(sessions):
    await _add(sessions, "t4", "agent:use", "*")
    pe = PolicyEngine(sessions)
    assert (await pe.is_allowed(Subject(tenant_id="t4", user_id="u"), "agent:use", "agent-123")).allowed


async def test_resource_scoped_allow_does_not_leak(sessions):
    await _add(sessions, "t5", "tool:execute", "calc.add")
    pe = PolicyEngine(sessions)
    assert not (await pe.is_allowed(Subject(tenant_id="t5", user_id="u"), "tool:execute", "http.get")).allowed
