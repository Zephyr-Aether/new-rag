"""Audit API（§6.7）：GET /audit 按租户/动作/资源/时间查询审计 + CSV 导出。"""

import csv
import io

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse

from app.state import AppState

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def query_audit(
    request: Request,
    tenant_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    resource: str | None = Query(default=None),
    since_hours: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    state: AppState = request.app.state.agent
    rows = await state.audit.list(
        tenant_id=tenant_id, action=action, resource=resource, since_hours=since_hours, limit=limit
    )
    return {"rows": rows, "total": len(rows)}


@router.get("/export")
async def export_audit_csv(
    request: Request,
    tenant_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    resource: str | None = Query(default=None),
    since_hours: int | None = Query(default=None, ge=1),
    limit: int = Query(default=500, ge=1, le=5000),
) -> PlainTextResponse:
    """审计导出 CSV（合规归档用）。"""
    state: AppState = request.app.state.agent
    rows = await state.audit.list(
        tenant_id=tenant_id, action=action, resource=resource, since_hours=since_hours, limit=limit
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time", "actor", "tenant", "action", "resource", "outcome", "detail"])
    for r in rows:
        w.writerow(
            [
                r.get("created_at") or "",
                r.get("actor_id") or "",
                r.get("tenant_id") or "",
                r.get("action") or "",
                r.get("resource") or "",
                r.get("outcome") or "",
                str(r.get("detail") or ""),
            ]
        )
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit.csv"},
    )
