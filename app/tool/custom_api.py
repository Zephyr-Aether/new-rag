"""自定义工具 API（页面录入沙箱代码工具）：读/存配置中心 + 热注册。

GET    /custom-tools            列出自定义工具（含注册状态）
PUT    /custom-tools            整单保存并 reconcile（新增/变更注册，删除注销）
DELETE /custom-tools/{ref}      删除单个工具并注销
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.state import AppState

router = APIRouter(prefix="/custom-tools", tags=["custom-tools"])

_CUSTOM_SCOPE = {"tenant_id": "", "scope": "CUSTOM_TOOLS", "scope_id": "default", "key": "defs"}


async def _get_defs(state: AppState) -> list[dict]:
    saved = await state.config_service.get(**_CUSTOM_SCOPE)
    value = (saved or {}).get("value") or []
    return value if isinstance(value, list) else []


class CustomToolDef(BaseModel):
    ref: str = Field(min_length=1)
    description: str = ""
    input_schema: dict = Field(default_factory=dict)
    code: str = Field(min_length=1)
    timeout_s: float = 5.0
    risk_level: str = "LOW_RISK_WRITE"  # READ / LOW_RISK_WRITE / HIGH_RISK_WRITE / CRITICAL


class CustomToolsRequest(BaseModel):
    tools: list[CustomToolDef] = Field(default_factory=list)


@router.get("")
async def list_custom_tools(request: Request) -> dict:
    state: AppState = request.app.state.agent
    return state.custom_tool_manager.list(await _get_defs(state))


@router.put("")
async def set_custom_tools(body: CustomToolsRequest, request: Request) -> dict:
    """整单保存自定义工具并热注册/注销，无需重启。"""
    state: AppState = request.app.state.agent
    defs = [d.model_dump() for d in body.tools if d.ref and d.code]
    await state.config_service.set(**_CUSTOM_SCOPE, value=defs)
    results = await state.custom_tool_manager.reconcile(defs)
    return {"ok": True, "count": len(defs), "results": results}


@router.delete("/{ref}")
async def delete_custom_tool(ref: str, request: Request) -> dict:
    state: AppState = request.app.state.agent
    defs = [d for d in await _get_defs(state) if d.get("ref") != ref]
    await state.config_service.set(**_CUSTOM_SCOPE, value=defs)
    await state.custom_tool_manager.unregister(ref)
    return {"ok": True, "deleted": ref}
