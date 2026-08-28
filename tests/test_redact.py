"""敏感数据脱敏（§13.3）：Redactor / SecretManager / 审计脱敏 / Secret Reference 注入。"""

import json

import pytest

from app.common.errors import AgentError
from app.security.redact import mask, mask_object
from app.security.secrets import SecretManager


def test_mask_secrets_and_pii():
    text = "api key=sk-abcdefghijklmnop123456, token=my-secret-token-9, phone=13812345678, mail=u@x.com"
    out = mask(text)
    assert "sk-abcdefghijklmnop123456" not in out
    assert "13812345678" not in out
    assert "u@x.com" not in out
    assert "sk-****" in out


def test_mask_object_recursive():
    obj = {"nested": {"token": "sk-abcdefghijklmnop123456"}, "list": ["13812345678"]}
    out = mask_object(obj)
    assert "sk-abcdefghijklmnop123456" not in out["nested"]["token"]
    assert "13812345678" not in out["list"][0]


def test_secret_manager_get_set():
    import asyncio

    sm = SecretManager()
    asyncio.run(sm.set("email-prod", "smtp://real-password"))
    assert sm.get("email-prod") == "smtp://real-password"
    assert sm.has("email-prod")
    with pytest.raises(AgentError):
        sm.get("missing-ref")


async def test_audit_detail_is_masked(audit):
    from sqlalchemy import select

    from app.storage.models import AuditLogRow

    await audit.record(
        tenant_id="t",
        actor_id="u",
        action="tool:execute",
        resource="http.get",
        outcome="SUCCEEDED",
        detail={"body": "token=sk-abcdefghijklmnop123456"},
    )
    async with audit.sessions() as s:
        row = (await s.scalars(select(AuditLogRow).where(AuditLogRow.action == "tool:execute"))).first()
    assert "sk-abcdefghijklmnop123456" not in row.detail_json
    assert "****" in row.detail_json  # 值被掩码（token=****）


async def test_secret_ref_injected_into_tool(sessions, policy, audit):
    """§6.5 Secret Reference：工具经 credential_ref 在执行时获取凭据，LLM/参数不可见。"""
    import uuid

    from app.agent.runtime.store import RunStore
    from app.common.contracts import ToolCallRequest
    from app.security.secrets import SecretManager, get_injected_secret
    from app.storage.models import PolicyRow
    from app.tool.limiter import RateLimiter
    from app.tool.registry import ToolDefinition, ToolRegistry
    from app.tool.runtime import ToolRuntime

    async with sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:8]}",
                tenant_id="t",
                name="mail-allow",
                effect="ALLOW",
                action="tool:execute",
                resource="send_email",
            )
        )
        await s.commit()

    sm = SecretManager()
    await sm.set("email-prod", "smtp://real-password")

    def _send_email(to, subject, body):
        return {"sent": True, "credential_used": get_injected_secret()}

    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            ref="send_email",
            description="x",
            input_schema={"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]},
            fn=_send_email,
            permission="send_email",
            credential_ref="email-prod",
        )
    )
    rt = ToolRuntime(
        registry=reg,
        policy=policy,
        audit=audit,
        limiter=RateLimiter(""),
        idem=RunStore(sessions),
        secret_manager=sm,
    )
    call = ToolCallRequest(
        call_id="s1",
        tenant_id="t",
        user_id="u",
        tool_ref="send_email",
        args={"to": "a@b.com", "subject": "hi", "body": "hello"},
    )
    res = await rt.execute(call)
    assert res.ok
    assert res.data["credential_used"] == "smtp://real-password"  # 执行时注入
    # LLM 参数里没有凭据，注入执行后已恢复
    assert "real-password" not in json.dumps(call.args, ensure_ascii=False)
    assert get_injected_secret() is None
