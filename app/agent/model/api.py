"""Model API（§52）：GET /model/health 健康 / GET /model/config 配置 / POST /model/config 运行时配置。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.deps import get_subject, require_perm
from app.state import AppState

router = APIRouter(prefix="/model", tags=["model"])

_MODEL_SCOPE = {"tenant_id": "", "scope": "MODEL", "scope_id": "default", "key": "config"}


class ModelConfigBody(BaseModel):
    provider: str  # mock | openai
    model: str = ""
    base_url: str = ""
    api_key: str = ""  # 可选；空 = 保留现有 key（不覆盖）


def _entry(m, h) -> dict:
    return {
        "model": m,
        "status": h.status(),
        "error_rate": round(h.error_rate(), 3),
        "rate_429": round(h.rate_429(), 3),
        "latency_p95_ms": round(h.latency_p95(), 1),
        "traffic_weight": h.traffic_weight(),
    }


@router.get("/health")
async def model_health(request: Request) -> dict:
    state: AppState = request.app.state.agent
    gw = state.gateway
    if gw.pool is not None:
        models = [_entry(f"provider-{i}", e.health) for i, e in enumerate(gw.pool.entries)]
    else:
        models = [_entry(gw.default_model, gw.health)]
    return {"models": models, "breaker": gw.breaker.state}


async def _saved_model_config(state: AppState) -> dict:
    saved = await state.config_service.get(**_MODEL_SCOPE)
    return (saved or {}).get("value") or {}


@router.get("/config")
async def model_config(request: Request) -> dict:
    """当前模型接入配置（不含密钥明文，仅 has_key）。页面配置优先，回落 .env settings。"""
    state: AppState = request.app.state.agent
    s = state.settings
    cfg = await _saved_model_config(state)
    provider = cfg.get("provider") or s.llm_provider
    model = cfg.get("model") or s.llm_model
    return {
        "provider": provider,
        "model": model,
        "base_url": cfg.get("base_url") or s.llm_base_url,
        "is_mock": provider == "mock",
        "has_key": bool(cfg.get("api_key") or s.llm_api_key),
        "saved": bool(cfg),
        "models": {
            "small": s.llm_model_small,
            "medium": s.llm_model_medium,
            "large": s.llm_model_large,
        },
    }


@router.post("/config")
async def set_model_config(
    body: ModelConfigBody,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("model:configure", "*"))],  # 权限 AOP
) -> dict:
    """运行时配置模型（存配置中心 + 即时生效）。api_key 可选，空则保留现有 key。"""
    state: AppState = request.app.state.agent
    try:
        state.gateway.configure(
            provider=body.provider,
            model=body.model,
            base_url=body.base_url,
            api_key=body.api_key or None,
        )
    except AgentError as exc:
        raise AgentError(exc.message, code="MODEL_CONFIG_INVALID", detail={"reason": exc.message}) from exc
    saved = body.model_dump()
    if not body.api_key:
        # 空 key = 不覆盖：保留已持久化的 key（页面留空保持不变）
        existing = await _saved_model_config(state)
        saved["api_key"] = existing.get("api_key", "")
    await state.config_service.set(**_MODEL_SCOPE, value=saved)
    return {"ok": True, **body.model_dump(), "is_mock": body.provider == "mock"}
