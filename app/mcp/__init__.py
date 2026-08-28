"""MCP 网关（§7.3）：把外部 MCP Server 的工具暴露为本地 ToolDefinition，Agent 可调用。

最小实现：MCP over HTTP JSON-RPC（tools/list + tools/call）。
安全：注册的工具带 permission（默认拒绝，须 policy 放行），risk_level 默认 READ。
"""

import json

import httpx

from app.tool.registry import ToolDefinition, ToolRegistry


class McpError(Exception):
    pass


class McpClient:
    """MCP HTTP JSON-RPC 客户端（tools/list + tools/call 最小集）。"""

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None, timeout_s: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._owned = client is None

    async def _request(self, method: str, params: dict) -> dict:
        resp = await self._client.post(
            f"{self.base_url}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("error"):
            raise McpError(body["error"].get("message", str(body["error"])))
        return body.get("result", {})

    async def list_tools(self) -> list[dict]:
        result = await self._request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> str:
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            text = " ".join(c.get("text", "") for c in result.get("content", []))
            raise McpError(text or f"mcp tool error: {name}")
        return "\n".join(c.get("text", "") for c in result.get("content", []))

    async def call_tool_stream(self, name: str, arguments: dict) -> str:
        """流式读取工具输出（§7.3 长输出按块累积，不整包等）。"""
        chunks: list[str] = []
        async with self._client.stream(
            "POST",
            f"{self.base_url}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line.startswith("event:") or line.startswith("data: [DONE]"):
                    continue
                if line.startswith("data:"):
                    line = line[len("data:") :].strip()
                chunks.append(line)
        return "\n".join(c for c in chunks if c)

    async def list_resources(self) -> list[dict]:
        """§7.3 MCP resources/list（可读资源）。"""
        result = await self._request("resources/list", {})
        return result.get("resources", [])

    async def read_resource(self, uri: str) -> str:
        result = await self._request("resources/read", {"uri": uri})
        contents = result.get("contents", [])
        return "\n".join(c.get("text", "") for c in contents)

    async def aclose(self) -> None:
        if self._owned:
            await self._client.aclose()


async def register_mcp_tools(
    registry: ToolRegistry,
    client: McpClient,
    *,
    prefix: str,
    permission: str,
    risk_level: str = "READ",
    allow_names: set[str] | None = None,
    max_output_chars: int = 8000,
) -> list[str]:
    """把 MCP server 的 tools 注册为 `prefix.name` 的代理工具。返回注册的 ref 列表。

    §7.2 安全：allow_names 为工具白名单（None=注册全部，显式名单只注册列出的）；
    max_output_chars 限制代理结果大小（防大 payload 撑爆 Context）。
    """
    refs: list[str] = []
    for tool in await client.list_tools():
        name = tool.get("name", "")
        if not name:
            continue
        if allow_names is not None and name not in allow_names:
            continue  # §7.2 白名单过滤：未列出的工具不注册
        ref = f"{prefix}.{name}"
        input_schema = tool.get("inputSchema") or {"type": "object", "properties": {}}

        async def _proxy(*, _mcp_name: str = name, **kwargs) -> str:
            text = await client.call_tool(_mcp_name, kwargs)
            # §7.2 输出上限：截断 + 标注（防超大 payload）
            if len(text) > max_output_chars:
                text = text[:max_output_chars] + "\n…[mcp output truncated]"
            return text

        registry.register(
            ToolDefinition(
                ref=ref,
                description=tool.get("description", "") or f"MCP tool {name}",
                input_schema=input_schema,
                fn=_proxy,
                risk_level=risk_level,
                permission=permission,
            )
        )
        refs.append(ref)
    return refs


def parse_mcp_servers(raw: str) -> dict[str, str]:
    """解析 settings.mcp_servers（JSON {name: base_url}）。"""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {k: v for k, v in parsed.items() if isinstance(v, str) and v}


async def register_resource_tools(
    registry: ToolRegistry,
    client: McpClient,
    *,
    prefix: str,
    permission: str,
    risk_level: str = "READ",
) -> list[str]:
    """§7.3 把 MCP 可读资源注册为 `prefix.resource.{name}` 读取工具。"""
    refs: list[str] = []
    for res in await client.list_resources():
        uri = res.get("uri", "")
        name = res.get("name") or uri
        if not uri:
            continue
        ref = f"{prefix}.resource.{name}"

        async def _read(*, _uri: str = uri, **kwargs) -> str:
            return await client.read_resource(_uri)

        registry.register(
            ToolDefinition(
                ref=ref,
                description=res.get("description", "") or f"MCP resource {name}",
                input_schema={"type": "object", "properties": {}},
                fn=_read,
                risk_level=risk_level,
                permission=permission,
            )
        )
        refs.append(ref)
    return refs


def parse_mcp_allowlist(raw: str) -> dict[str, set[str]]:
    """解析 settings.mcp_tool_allowlist（JSON {server: [tool_name, ...]}）。"""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {k: {t for t in v if isinstance(t, str)} for k, v in parsed.items() if isinstance(v, list)}
