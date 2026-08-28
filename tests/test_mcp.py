"""MCP 网关（§7.2/§7.3）：外部 MCP server 工具注册为本地代理工具 + 白名单 + 输出上限。"""

import json
import uuid

import httpx
import pytest

from app.common.contracts import ToolCallRequest
from app.mcp import (
    McpClient,
    parse_mcp_allowlist,
    parse_mcp_servers,
    register_mcp_tools,
    register_resource_tools,
)
from app.storage.models import PolicyRow
from app.tool.registry import ToolNotFoundError, default_registry
from app.tool.runtime import ToolRuntime


def _mock_client() -> McpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "tools/list":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "tools": [
                            {
                                "name": "weather",
                                "description": "查天气",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"city": {"type": "string"}},
                                    "required": ["city"],
                                },
                            }
                        ]
                    },
                },
            )
        args = body["params"]["arguments"]
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": f"weather({args.get('city')})"}]},
            },
        )

    return McpClient("http://mcp.local", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_mcp_tools_registered_and_proxied():
    client = _mock_client()
    reg = default_registry()
    refs = await register_mcp_tools(reg, client, prefix="ext", permission="mcp:ext")
    assert refs == ["ext.weather"]
    tool = reg.resolve("ext.weather")
    assert tool.permission == "mcp:ext"
    result = await tool.fn(city="北京")
    assert result == "weather(北京)"
    await client.aclose()


async def test_mcp_tool_via_runtime(sessions, policy, audit, rate_limiter, store):
    async with sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:8]}",
                tenant_id="t",
                name="mcp-allow",
                effect="ALLOW",
                action="tool:execute",
                resource="ext.weather",
            )
        )
        await s.commit()
    client = _mock_client()
    reg = default_registry()
    await register_mcp_tools(reg, client, prefix="ext", permission="mcp:ext")
    rt = ToolRuntime(registry=reg, policy=policy, audit=audit, limiter=rate_limiter, idem=store)
    res = await rt.execute(
        ToolCallRequest(
            call_id="m1", tenant_id="t", user_id="u", tool_ref="ext.weather", args={"city": "北京"}
        )
    )
    assert res.ok and res.data == "weather(北京)"
    await client.aclose()


async def test_mcp_allowlist_filters():
    """§7.2 白名单：未列出的工具不注册（只注册 weather）。"""
    client = _mock_client()
    reg = default_registry()
    refs = await register_mcp_tools(reg, client, prefix="ext", permission="mcp:ext", allow_names={"weather"})
    assert refs == ["ext.weather"]
    await client.aclose()

    client2 = _mock_client()
    reg2 = default_registry()
    refs2 = await register_mcp_tools(reg2, client2, prefix="ext", permission="mcp:ext", allow_names={"nope"})
    assert refs2 == []  # 白名单没命中 => 不注册任何工具
    with pytest.raises(ToolNotFoundError):
        reg2.resolve("ext.weather")
    await client2.aclose()


async def test_mcp_output_truncated():
    """§7.2 输出上限：超长结果截断 + 标注。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "tools/list":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"tools": [{"name": "big", "inputSchema": {"type": "object"}}]},
                },
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "y" * 5000}]}},
        )

    client = McpClient("http://mcp.local", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    reg = default_registry()
    await register_mcp_tools(reg, client, prefix="ext", permission="mcp:ext", max_output_chars=100)
    tool = reg.resolve("ext.big")
    text = await tool.fn()
    assert "[mcp output truncated]" in text
    assert len(text) <= 100 + len("…[mcp output truncated]") + 1
    await client.aclose()


def test_parse_helpers():
    assert parse_mcp_servers('{"a": "http://x"}') == {"a": "http://x"}
    assert parse_mcp_servers("bad json") == {}
    assert parse_mcp_allowlist('{"ext": ["weather"]}') == {"ext": {"weather"}}
    assert parse_mcp_allowlist('{"ext": "not-list"}') == {}


class _ResourcesClient:
    async def list_resources(self):
        return [{"uri": "docs://manual", "name": "manual", "description": "操作手册"}]

    async def read_resource(self, uri):
        return f"resource({uri})"

    async def aclose(self):
        pass


async def test_mcp_resources_registered():
    """§7.3 资源读取工具注册为 `prefix.resource.{name}`。"""
    reg = default_registry()
    refs = await register_resource_tools(reg, _ResourcesClient(), prefix="ext", permission="mcp:ext")
    assert refs == ["ext.resource.manual"]
    tool = reg.resolve("ext.resource.manual")
    assert await tool.fn() == "resource(docs://manual)"
