"""Config / Flag API（§30）：
GET  /config             读最新配置（scope/scope_id/key）
POST /config             写配置（新版本）
GET  /config/{key}/versions/{version}   读指定版本（回滚）
POST /flags              设置 Feature Flag
GET  /flags/{key}        判断 Flag 是否放量
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.common.contracts import Subject
from app.gateway.deps import get_subject, require_perm
from app.state import AppState

router = APIRouter(prefix="", tags=["config"])


class ConfigWrite(BaseModel):
    scope: str = "GLOBAL"
    scope_id: str = ""
    key: str
    value: object


class FlagWrite(BaseModel):
    key: str
    rules: dict = {}
    enabled: bool = True


@router.get("/config")
async def get_config(
    request: Request,
    key: str,
    scope: str = "GLOBAL",
    scope_id: str = "",
) -> dict:
    state: AppState = request.app.state.agent
    row = await state.config_service.get(
        tenant_id=state.seed["tenant_id"], scope=scope, scope_id=scope_id, key=key
    )
    return row or {"key": key, "value": None, "version": None}


@router.post("/config")
async def set_config(
    body: ConfigWrite, request: Request, _: Annotated[Subject, Depends(require_perm("config:write", "*"))]
) -> dict:
    state: AppState = request.app.state.agent
    return await state.config_service.set(
        tenant_id=state.seed["tenant_id"],
        scope=body.scope,
        scope_id=body.scope_id,
        key=body.key,
        value=body.value,
    )


@router.get("/config/{key}/versions/{version}")
async def get_config_version(
    key: str, version: int, request: Request, scope: str = "GLOBAL", scope_id: str = ""
) -> dict:
    state: AppState = request.app.state.agent
    row = await state.config_service.get_version(
        tenant_id=state.seed["tenant_id"], scope=scope, scope_id=scope_id, key=key, version=version
    )
    return row or {"key": key, "value": None, "version": None}


@router.post("/flags")
async def set_flag(
    body: FlagWrite,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("flags:write", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    return await state.flag_service.set_flag(
        tenant_id=subject.tenant_id, key=body.key, rules=body.rules, enabled=body.enabled
    )


@router.get("/flags/{key}")
async def flag_enabled(key: str, request: Request, subject: Annotated[Subject, Depends(get_subject)]) -> dict:
    state: AppState = request.app.state.agent
    enabled = await state.flag_service.is_enabled(
        tenant_id=subject.tenant_id, key=key, user_id=subject.user_id
    )
    return {"key": key, "enabled": enabled}
