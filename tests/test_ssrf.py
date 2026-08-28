"""SSRF 防护（§38）：http.get 阻断内网/回环/保留地址。"""

import pytest

from app.common.contracts import Subject, ToolCallRequest
from app.common.errors import ToolInvalidArgumentError
from app.tool.registry import default_registry, execute_tool


async def test_ssrf_blocks_loopback(store):
    tool = default_registry().resolve("http.get")
    with pytest.raises(ToolInvalidArgumentError):
        await execute_tool(
            tool,
            {"url": "http://127.0.0.1:9/foo"},
            call_id="s1",
            subject=Subject(tenant_id="t", user_id="u"),
            idem=store,
        )


async def test_ssrf_blocks_private_range(store):
    tool = default_registry().resolve("http.get")
    with pytest.raises(ToolInvalidArgumentError):
        await execute_tool(
            tool,
            {"url": "http://10.0.0.5/foo"},
            call_id="s2",
            subject=Subject(tenant_id="t", user_id="u"),
            idem=store,
        )


async def test_non_http_scheme_rejected(store):
    tool = default_registry().resolve("http.get")
    with pytest.raises(ToolInvalidArgumentError):
        await execute_tool(
            tool,
            {"url": "file:///etc/passwd"},
            call_id="s3",
            subject=Subject(tenant_id="t", user_id="u"),
            idem=store,
        )


async def test_ssrf_blocked_via_tool_runtime(tool_runtime):
    call = ToolCallRequest(
        call_id="s4", tenant_id="t", user_id="u", tool_ref="http.get", args={"url": "http://127.0.0.1:9/foo"}
    )
    with pytest.raises(ToolInvalidArgumentError):
        await tool_runtime.execute(call)
