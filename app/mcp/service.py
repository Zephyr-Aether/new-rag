"""MCP 服务器运行时管理器（页面接入）：把配置中心里的 MCP server 热注册/注销到工具注册表。

- 启动与页面保存时 reconcile：新增/变更的 server 连接并注册其工具，被删/停用的注销；
- 注册后自动给默认租户加 ALLOW 策略（`tool:execute -> mcp:{name}`），否则 default-deny 无法执行；
- 客户端连接在 manager 内持有，退出时统一关闭。
"""

import uuid

from sqlalchemy import select

from app.mcp import McpClient, register_mcp_tools
from app.storage.models import PolicyRow
from app.tool.registry import ToolRegistry


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class McpManager:
    def __init__(self, registry: ToolRegistry, sessions, seed_tenant: str, max_output_chars: int = 8000):
        self.registry = registry
        self.sessions = sessions
        self.seed_tenant = seed_tenant
        self.max_output_chars = max_output_chars
        self.clients: dict[str, McpClient] = {}
        self.server_tools: dict[str, list[str]] = {}

    async def reconcile(self, config: dict[str, dict]) -> dict:
        """按配置清单对齐注册表。config: {name: {"base_url", "allow", "enabled"}}。返回每 server 的结果。"""
        results: dict[str, str] = {}
        # 注销：已注册但配置里已删除/停用
        for name in list(self.server_tools):
            cfg = config.get(name)
            if cfg is None or not cfg.get("enabled", True):
                await self.unregister(name)
                results[name] = "removed"
        # 注册 / 更新
        for name, cfg in config.items():
            if not cfg.get("enabled", True):
                continue
            base_url = str(cfg.get("base_url") or "").strip()
            if not base_url:
                continue
            client = self.clients.get(name)
            if client is not None and client.base_url == base_url.rstrip("/"):
                results[name] = "unchanged"
                continue
            await self.unregister(name)
            try:
                refs = await self.register(name, base_url, allow=cfg.get("allow") or [])
                results[name] = f"registered {len(refs)} tools"
            except Exception as exc:  # noqa: BLE001 单 server 失败不阻断其它
                results[name] = f"failed: {exc}"
        return results

    async def register(self, name: str, base_url: str, *, allow: list[str]) -> list[str]:
        """连接并注册一个 MCP server 的工具，返回注册的 ref 列表。"""
        client = McpClient(base_url)
        await client.list_tools()  # 连通性验证（失败即抛，由调用方捕获）
        self.clients[name] = client
        allow_names = {a for a in allow if a} or None
        refs = await register_mcp_tools(
            self.registry,
            client,
            prefix=name,
            permission=f"mcp:{name}",
            allow_names=allow_names,
            max_output_chars=self.max_output_chars,
        )
        self.server_tools[name] = refs
        await self._ensure_allow_policies(refs)
        return refs

    async def unregister(self, name: str) -> None:
        for ref in self.server_tools.pop(name, []):
            try:
                self.registry.unregister(ref)
            except Exception:  # noqa: BLE001
                pass
        client = self.clients.pop(name, None)
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass

    async def _ensure_allow_policies(self, refs: list[str]) -> None:
        """给默认租户加 ALLOW：`tool:execute -> {tool.ref}`（default-deny 下才能执行）。"""
        async with self.sessions() as s:
            for ref in refs:
                existing = await s.scalar(
                    select(PolicyRow)
                    .where(
                        PolicyRow.tenant_id == self.seed_tenant,
                        PolicyRow.effect == "ALLOW",
                        PolicyRow.action == "tool:execute",
                        PolicyRow.resource == ref,
                    )
                    .limit(1)
                )
                if existing is not None:
                    continue
                s.add(
                    PolicyRow(
                        id=_uid("pol"),
                        tenant_id=self.seed_tenant,
                        name=f"mcp-allow-{ref}",
                        effect="ALLOW",
                        action="tool:execute",
                        resource=ref,
                    )
                )
            await s.commit()

    async def list(self, config: dict[str, dict]) -> dict:
        servers = []
        for name, cfg in config.items():
            servers.append(
                {
                    "name": name,
                    "base_url": cfg.get("base_url", ""),
                    "allow": cfg.get("allow") or [],
                    "enabled": cfg.get("enabled", True),
                    "registered": name in self.server_tools,
                    "tools": self.server_tools.get(name, []),
                }
            )
        return {"servers": servers}

    async def close(self) -> None:
        for name in list(self.server_tools):
            await self.unregister(name)
