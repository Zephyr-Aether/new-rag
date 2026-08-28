"""会话管理 API（§10 对话产品化）：持久化消息 + 会话列表/加载/重命名/删除。

GET    /sessions                当前用户会话列表（标题/条数/末条预览）
GET    /sessions/{id}/messages  加载会话消息（重建多轮上下文）
PATCH  /sessions/{id}           重命名 / 归档
DELETE /sessions/{id}           删除会话（连同消息）
"""

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.deps import get_subject
from app.state import AppState
from app.storage.models import MessageRow, SessionRow

router = APIRouter(prefix="/sessions", tags=["sessions"])

logger = logging.getLogger(__name__)


class SessionPatch(BaseModel):
    title: str | None = None
    status: str | None = None


@router.get("")
async def list_sessions(
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        sessions = (
            await s.scalars(
                select(SessionRow)
                .where(SessionRow.tenant_id == subject.tenant_id, SessionRow.user_id == subject.user_id)
                .order_by(SessionRow.created_at.desc())
                .limit(100)
            )
        ).all()
        ids = [x.id for x in sessions]
        msgs: list[MessageRow] = []
        if ids:
            msgs = (
                await s.scalars(
                    select(MessageRow)
                    .where(MessageRow.session_id.in_(ids))
                    .order_by(MessageRow.session_id, MessageRow.seq)
                )
            ).all()
    count_by_sid: dict[str, int] = {}
    last_by_sid: dict[str, str] = {}
    for m in msgs:
        count_by_sid[m.session_id] = count_by_sid.get(m.session_id, 0) + 1
        last_by_sid[m.session_id] = m.content
    return {
        "sessions": [
            {
                "id": x.id,
                "title": x.title or "新会话",
                "status": x.status,
                "created_at": x.created_at.isoformat() if x.created_at else None,
                "message_count": count_by_sid.get(x.id, 0),
                "last_content": (last_by_sid.get(x.id) or "")[:80],
            }
            for x in sessions
        ]
    }


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        session = await s.get(SessionRow, session_id)
        if session is None or session.tenant_id != subject.tenant_id:
            raise AgentError("session not found", code="SESSION_NOT_FOUND")
        rows = (
            await s.scalars(
                select(MessageRow).where(MessageRow.session_id == session_id).order_by(MessageRow.seq)
            )
        ).all()
        return {
            "session_id": session_id,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "tools": json.loads(m.tools_json or "[]"),
                    "docs": json.loads(m.docs_json or "[]"),
                }
                for m in rows
            ],
        }


@router.delete("/{session_id}/messages/{message_id}")
async def delete_session_message(
    session_id: str,
    message_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """删除会话中的单条消息（§10 对话管理）。"""
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        session = await s.get(SessionRow, session_id)
        if session is None or session.tenant_id != subject.tenant_id:
            raise AgentError("session not found", code="SESSION_NOT_FOUND")
        row = await s.get(MessageRow, message_id)
        if row is None or row.session_id != session_id:
            raise AgentError("message not found", code="MESSAGE_NOT_FOUND")
        await s.delete(row)
        await s.commit()
    return {"ok": True, "deleted": message_id}


@router.patch("/{session_id}")
async def patch_session(
    session_id: str,
    body: SessionPatch,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        session = await s.get(SessionRow, session_id)
        if session is None or session.tenant_id != subject.tenant_id:
            raise AgentError("session not found", code="SESSION_NOT_FOUND")
        if body.title is not None:
            session.title = body.title
        if body.status is not None:
            session.status = body.status
        await s.commit()
    return {"ok": True, "id": session_id}


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        session = await s.get(SessionRow, session_id)
        if session is None or session.tenant_id != subject.tenant_id:
            raise AgentError("session not found", code="SESSION_NOT_FOUND")
        await s.execute(delete(MessageRow).where(MessageRow.session_id == session_id))
        await s.delete(session)
        await s.commit()
    return {"ok": True, "deleted": session_id}


async def persist_chat_messages(state: AppState, run_id: str) -> None:
    """run 完成后把 user/assistant 消息（含工具摘要）写入会话，支撑对话历史持久化。"""
    try:
        run = await state.store.get_run(run_id)
        if run is None or not run.get("session_id"):
            return
        session_id = run["session_id"]
        input_json = json.loads(run.get("input_json") or "{}")
        output_json = json.loads(run.get("output_json") or "{}")
        user_text = (input_json.get("text") or "").strip()
        answer = output_json.get("answer") or ""
        steps = await state.store.list_steps(run_id)
        tools = []
        docs: list[str] = []
        for st in steps:
            for tc in st.get("tool_calls") or []:
                tools.append({"tool_ref": tc.get("tool_ref"), "ok": bool(tc.get("ok"))})
                data = tc.get("data")
                if isinstance(data, list):  # 检索类工具：提取命中文档 id（引用来源）
                    for c in data:
                        if isinstance(c, dict) and c.get("document_id"):
                            docs.append(c["document_id"])
        docs = sorted(set(docs))
        async with state.sessions() as s:
            session = await s.get(SessionRow, session_id)
            if session is None:
                return
            if not session.title and user_text:
                session.title = user_text[:40]
            n = await s.scalar(select(func.max(MessageRow.seq)).where(MessageRow.session_id == session_id))
            seq0 = int(n) + 1 if n is not None else 0  # MAX(seq)+1：删除消息后不冲突
            s.add(
                MessageRow(
                    id=f"msg-{uuid.uuid4().hex[:12]}",
                    session_id=session_id,
                    role="user",
                    content=user_text,
                    tools_json="[]",
                    seq=seq0,
                )
            )
            s.add(
                MessageRow(
                    id=f"msg-{uuid.uuid4().hex[:12]}",
                    session_id=session_id,
                    role="assistant",
                    content=answer,
                    tools_json=json.dumps(tools, ensure_ascii=False),
                    docs_json=json.dumps(docs, ensure_ascii=False),
                    seq=seq0 + 1,
                )
            )
            await s.commit()
    except Exception:  # noqa: BLE001 对话持久化失败不影响主流程
        logger.warning("persist chat messages failed: %s", run_id, exc_info=True)
