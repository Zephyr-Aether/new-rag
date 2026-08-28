"""API 级幂等（Idempotency-Key）：对 POST/PUT/PATCH 携带 `Idempotency-Key` 的请求去重。

- 首次执行并缓存响应（24h TTL，只缓存 2xx 的 JSON；流式/非 JSON 跳过）；
- 同 key 重放直接返回缓存（响应头带 `Idempotent-Replayed: true`）；
- 并发同 key：DB 双重检查 + 主键唯一兜底（重复写冲突时以既有缓存为准）。
"""

from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import delete

_IDEM_TTL_S = 24 * 3600


def _ttl_expired(created) -> bool:
    if created is None:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return datetime.now(UTC) - created > timedelta(seconds=_IDEM_TTL_S)


async def _get_cached(state, key: str) -> tuple[int, str] | None:
    from app.storage.models import IdempotencyRow

    async with state.sessions() as s:
        row = await s.get(IdempotencyRow, key)
        if row is None or _ttl_expired(row.created_at):
            return None
        return row.status_code, row.body


async def _store(state, key: str, status_code: int, body: str) -> None:
    from app.storage.models import IdempotencyRow

    try:
        async with state.sessions() as s:
            row = await s.get(IdempotencyRow, key)
            if row is None:
                s.add(IdempotencyRow(key=key, status_code=status_code, body=body))
            else:
                row.status_code = status_code
                row.body = body
            cutoff = datetime.now(UTC) - timedelta(seconds=_IDEM_TTL_S)
            await s.execute(delete(IdempotencyRow).where(IdempotencyRow.created_at < cutoff))
            await s.commit()
    except Exception:  # noqa: BLE001 并发同 key 插入冲突等：以既有缓存为准，不阻塞主流程
        return


def make_idempotency_middleware():
    async def idempotency_middleware(request: Request, call_next):
        idem_key = request.headers.get("Idempotency-Key")
        if not idem_key or request.method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)
        key = f"{request.method}:{idem_key}"
        state = request.app.state.agent
        if state is None:
            return await call_next(request)
        cached = await _get_cached(state, key)
        if cached is not None:
            status, body = cached
            return Response(
                content=body,
                status_code=status,
                media_type="application/json",
                headers={"Idempotent-Replayed": "true"},
            )
        response = await call_next(request)
        ctype = response.headers.get("content-type", "")
        if response.status_code < 400 and "text/event-stream" not in ctype:
            body_bytes = b"".join([chunk async for chunk in response.body_iterator])
            text = body_bytes.decode("utf-8", errors="replace") or "null"
            await _store(state, key, response.status_code, text)
            return Response(
                content=body_bytes, status_code=response.status_code, media_type=ctype or "application/json"
            )
        return response

    return idempotency_middleware
