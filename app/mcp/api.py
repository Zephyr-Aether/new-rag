"""MCP 服务器管理 API（页面接入）：读/存配置中心 + 热注册到工具表。

GET    /mcp/servers            列出已配置的 MCP server（含注册状态与工具）
PUT    /mcp/servers            整单保存并 reconcile（新增/变更注册，删除/停用注销）
DELETE /mcp/servers/{name}     删除单个 server 并注销其工具
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.state import AppState

router = APIRouter(prefix="/mcp", tags=["mcp"])

_MCP_SCOPE = {"tenant_id": "", "scope": "MCP", "scope_id": "default", "key": "servers"}


async def _get_config(state: AppState) -> dict:
    saved = await state.config_service.get(**_MCP_SCOPE)
    value = (saved or {}).get("value") or {}
    return value if isinstance(value, dict) else {}


class McpServerDef(BaseModel):
    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    allow: list[str] = Field(default_factory=list)
    enabled: bool = True


class McpServersRequest(BaseModel):
    servers: list[McpServerDef] = Field(default_factory=list)


@router.get("/servers")
async def list_mcp_servers(request: Request) -> dict:
    state: AppState = request.app.state.agent
    return await state.mcp_manager.list(await _get_config(state))


@router.put("/servers")
async def set_mcp_servers(body: McpServersRequest, request: Request) -> dict:
    """整单保存 MCP server 配置并热注册/注销，无需重启。"""
    state: AppState = request.app.state.agent
    config = {
        s.name.strip(): {
            "base_url": s.base_url.strip(),
            "allow": [a for a in s.allow if a],
            "enabled": s.enabled,
        }
        for s in body.servers
        if s.name.strip() and s.base_url.strip()
    }
    await state.config_service.set(**_MCP_SCOPE, value=config)
    results = await state.mcp_manager.reconcile(config)
    return {"ok": True, "count": len(config), "results": results}


@router.delete("/servers/{name}")
async def delete_mcp_server(name: str, request: Request) -> dict:
    state: AppState = request.app.state.agent
    config = await _get_config(state)
    config.pop(name, None)
    await state.config_service.set(**_MCP_SCOPE, value=config)
    await state.mcp_manager.unregister(name)
    return {"ok": True, "deleted": name}
