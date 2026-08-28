"""Queue Admin API（§9）：任务查看 / DLQ 重放。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.common.contracts import Subject
from app.gateway.deps import require_perm
from app.state import AppState

router = APIRouter(prefix="/queue", tags=["queue"])


@router.get("/jobs")
async def list_jobs(
    request: Request,
    state: str = Query(default="DEAD_LETTER"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    app_state: AppState = request.app.state.agent
    job_ids = await app_state.job_queue.store.list_in_state(state)
    rows = []
    for job_id in job_ids[:limit]:
        row = await app_state.job_queue.store.get(job_id)
        if row:
            rows.append(
                {
                    "job_id": row["job_id"],
                    "job_type": row["job_type"],
                    "state": row["state"],
                    "attempts": row["attempts"],
                    "error": row["error"],
                }
            )
    return {"rows": rows, "total": len(rows), "state": state}


@router.get("/stats")
async def queue_stats(request: Request) -> dict:
    """队列统计：按状态/类型计数 + 近 24h 每小时创建量 + 采样深度趋势（监控图用）。"""
    app_state: AppState = request.app.state.agent
    stats = await app_state.job_queue.store.stats()
    stats["depth"] = await app_state.job_queue.store.depth_trend(24)
    return stats


@router.post("/sample")
async def sample_queue(request: Request) -> dict:
    """手动落一次队列深度采样（后台也会定时采样）。"""
    app_state: AppState = request.app.state.agent
    stats = await app_state.job_queue.store.stats()
    await app_state.job_queue.store.save_sample(stats)
    return {"ok": True, "total": stats["total"]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict:
    """任务详情下钻：完整字段（payload/重试/租约/时间线）。"""
    app_state: AppState = request.app.state.agent
    row = await app_state.job_queue.store.get(job_id)
    if row is None:
        from app.common.errors import AgentError

        raise AgentError(f"job not found: {job_id}", code="JOB_NOT_FOUND")
    return row


@router.post("/jobs/{job_id}/requeue")
async def requeue_job(
    job_id: str, request: Request, _: Annotated[Subject, Depends(require_perm("queue:ops", "*"))]
) -> dict:
    """DLQ 重放：DEAD_LETTER 任务重置并入堆（可再次执行）。"""
    app_state: AppState = request.app.state.agent
    return await app_state.job_queue.requeue(job_id)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str, request: Request, _: Annotated[Subject, Depends(require_perm("queue:ops", "*"))]
) -> dict:
    """§11.2 取消排队任务（CREATED/QUEUED -> CANCELLED）。"""
    app_state: AppState = request.app.state.agent
    return await app_state.job_queue.cancel(job_id)


@router.post("/jobs/expire")
async def expire_jobs(
    request: Request,
    _: Annotated[Subject, Depends(require_perm("queue:ops", "*"))],
    ttl_s: int = Query(default=3600, ge=1),
) -> dict:
    """§11.2 清理超龄 QUEUED 任务（EXPIRED）。"""
    app_state: AppState = request.app.state.agent
    return await app_state.job_queue.expire_old(ttl_s)
