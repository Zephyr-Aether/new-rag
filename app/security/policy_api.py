"""策略管理 API（§6.2）：租户/用户级策略的查看与维护（配合 require_perm AOP）。

GET    /policies           列出当前租户的策略（租户级 + 用户级）
POST   /policies           新增策略（user_id 留空=租户级，非空=用户级）
GET    /policies/meta      策略表单下拉数据：可用 action 清单 + 已用 resource 集合
PUT    /policies/{id}      编辑策略
DELETE /policies/{id}      删除策略
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.deps import require_perm
from app.state import AppState
from app.storage.models import PolicyRow

router = APIRouter(prefix="/policies", tags=["policies"])

# 代码库中所有 require_perm 注册过的权限动作，作为策略表单下拉数据。
PERM_ACTIONS: tuple[str, ...] = (
    "config:write",
    "cost:reconcile",
    "data:purge",
    "eval:write",
    "flags:write",
    "graph:write",
    "kb:ingest",
    "memory:write",
    "model:configure",
    "policy:manage",
    "queue:ops",
    "release:ops",
    "release:publish",
    "release:version:create",
)

# 动作中文名（前端下拉展示用）；未收录的动作回退为原值。
PERM_ACTION_NAMES: dict[str, str] = {
    "config:write": "配置写入",
    "cost:reconcile": "成本对账",
    "data:purge": "数据清理",
    "eval:write": "评测写入",
    "flags:write": "特性开关",
    "graph:write": "图谱写入",
    "kb:ingest": "知识库入库",
    "memory:write": "记忆写入",
    "model:configure": "模型配置",
    "policy:manage": "策略管理",
    "queue:ops": "队列运维",
    "release:ops": "发布运维",
    "release:publish": "发布执行",
    "release:version:create": "创建发布版本",
}

# 常见资源中文名（前端下拉展示用）；未收录的资源 name 为 null，前端只显示原代码。
RESOURCE_NAMES: dict[str, str] = {
    "*": "所有资源",
    "calc.add": "求和计算",
    "calc.fib": "斐波那契",
    "echo": "回显",
    "http.get": "HTTP 请求",
    "kb.search": "知识库检索",
    "graph.query": "图谱查询",
    "ext.get_time": "获取时间",
    "ext.quote": "名言引用",
    "ext.translate": "翻译",
    "ext.weather": "天气查询",
    "text.stats": "文本统计",
}


class PolicyRequest(BaseModel):
    action: str
    resource: str = "*"
    effect: str = "ALLOW"  # ALLOW / DENY
    user_id: str | None = None  # 非空=用户级
    role_id: str | None = None  # 非空=角色级
    name: str = ""


@router.get("")
async def list_policies(
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        rows = await s.scalars(
            select(PolicyRow)
            .where(PolicyRow.tenant_id == subject.tenant_id)
            .order_by(PolicyRow.user_id, PolicyRow.action, PolicyRow.resource)
        )
        return {
            "policies": [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "role_id": r.role_id,
                    "name": r.name,
                    "effect": r.effect,
                    "action": r.action,
                    "resource": r.resource,
                    "enabled": r.enabled,
                }
                for r in rows
            ]
        }


@router.get("/meta")
async def policy_meta(
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    """策略表单下拉数据：可用 action 清单 + 本租户已用的 resource 集合（含 *）。"""
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        res = await s.scalars(
            select(PolicyRow.resource).where(PolicyRow.tenant_id == subject.tenant_id).distinct()
        )
        resources = sorted({"*"} | {r for r in res if r})
    return {
        "actions": [{"action": a, "name": PERM_ACTION_NAMES.get(a, a)} for a in PERM_ACTIONS],
        "resources": [{"resource": r, "name": RESOURCE_NAMES.get(r)} for r in resources],
    }


@router.post("")
async def create_policy(
    body: PolicyRequest,
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:12]}",
                tenant_id=subject.tenant_id,
                user_id=body.user_id,
                role_id=body.role_id,
                name=body.name or f"{body.effect.lower()}-{body.action}:{body.resource}",
                effect=body.effect.upper(),
                action=body.action,
                resource=body.resource,
            )
        )
        await s.commit()
    return {"ok": True}


@router.put("/{policy_id}")
async def update_policy(
    policy_id: str,
    body: PolicyRequest,
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    """编辑策略：更新动作/资源/效果/作用域。"""
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        row = await s.get(PolicyRow, policy_id)
        if row is None or row.tenant_id != subject.tenant_id:
            raise AgentError("policy not found", code="POLICY_NOT_FOUND")
        row.action = body.action
        row.resource = body.resource
        row.effect = body.effect.upper()
        row.user_id = body.user_id
        row.role_id = body.role_id
        row.name = body.name or row.name
        await s.commit()
    return {"ok": True, "id": policy_id}


@router.delete("/{policy_id}")
async def delete_policy(
    policy_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        row = await s.get(PolicyRow, policy_id)
        if row is None or row.tenant_id != subject.tenant_id:
            raise AgentError("policy not found", code="POLICY_NOT_FOUND")
        await s.delete(row)
        await s.commit()
    return {"ok": True, "deleted": policy_id}
