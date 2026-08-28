"""Runs API（§32 的 MVP 子集）：

POST /runs               发起一次 Agent Run（默认同步返回结果；await_result=false 走队列异步）
GET  /runs/{run_id}      查询 Run + Steps（可观测/排障）
POST /runs/{run_id}/cancel   请求取消（协作式）
"""

import asyncio
import difflib
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.agent.api.sessions import persist_chat_messages
from app.agent.runtime.budget import ExecutionBudget, default_budget_from_settings
from app.agent.runtime.runtime import RuntimeDeps, execute_run, resume_run
from app.common.contracts import RunInput, RunResult, Subject
from app.common.errors import AgentError
from app.gateway.deps import get_subject
from app.security.redact import mask_object
from app.state import AppState
from app.storage.models import AgentRow, AgentVersionRow, SessionRow

router = APIRouter(prefix="/runs", tags=["runs"])


class RunCreateRequest(BaseModel):
    input: str
    agent_id: str | None = None
    session_id: str | None = None
    model: str | None = None
    await_result: bool = True
    history: list[dict] | None = None  # §10 对话多轮：前序 user/assistant 消息


class ReplayRequest(BaseModel):
    model: str | None = None
    system_prompt: str | None = None
    top_k: int | None = None  # §60 换检索参数（kb.search top_k 覆盖）


def _deps(state: AppState) -> RuntimeDeps:
    return RuntimeDeps(
        store=state.store,
        registry=state.registry,
        gateway=state.gateway,
        lock=state.lock,
        cancel=state.cancel,
        tool_runtime=state.tool_runtime,
        payload_recorder=state.payload_recorder,
        memory_service=state.memory_service,  # §12.4 记忆自动使用
    )


async def _resolve_agent(
    state: AppState, tenant_id: str, agent_id: str | None, user_id: str | None = None
) -> tuple[str, int, str, str, str]:
    """§21 通过 ReleaseService.resolve 解析生效版本（支持灰度命中），返回含 release_status。"""
    async with state.sessions() as s:
        if agent_id:
            agent = await s.get(AgentRow, agent_id)
        else:
            agent = await s.scalar(
                select(AgentRow).where(AgentRow.tenant_id == tenant_id, AgentRow.slug == "assistant")
            )
        if agent is None:
            raise AgentError(f"agent not found: {agent_id or 'assistant'}", code="AGENT_NOT_FOUND")
    resolved = await state.release.resolve(tenant_id=tenant_id, agent_id=agent.id, user_id=user_id)
    return (
        agent.id,
        resolved["version"],
        resolved["system_prompt"],
        resolved["model"] or state.gateway.default_model,  # §8 运行时配置优先于 .env
        resolved["status"],
    )


async def _build_frozen(
    state: AppState, tenant_id: str, agent_id: str, version: int, release_status: str
) -> dict:
    """§22.1 版本冻结：从版本 config 冻结 tool/knowledge 版本集（运行中绝不漂移）。"""
    async with state.sessions() as s:
        row = await s.scalar(
            select(AgentVersionRow).where(
                AgentVersionRow.tenant_id == tenant_id,
                AgentVersionRow.agent_id == agent_id,
                AgentVersionRow.version == version,
            )
        )
    cfg = json.loads(row.config_json or "{}") if row else {}
    tools = {}
    for ref in cfg.get("tools", []):
        try:
            tools[ref] = state.registry.resolve(ref).version
        except Exception:  # noqa: BLE001 未注册工具：执行时仍会失败，这里不阻断
            tools[ref] = "unknown"
    return {
        "agent_version": version,
        "release_status": release_status,
        "tools": tools,
        "knowledge_version": cfg.get("knowledge_version", "0"),
    }


async def _enforce_tenant_quota(state: AppState, tenant_id: str, limit: int | None = None) -> None:
    """§16.3 租户并发 run 配额：超限拒绝（TENANT_RUN_QUOTA）。"""
    quota = limit if limit is not None else state.settings.tenant_max_concurrent_runs
    active = await state.store.count_active_runs(tenant_id)
    if active >= quota:
        raise AgentError(
            f"tenant run quota exceeded: {active}/{quota}",
            code="TENANT_RUN_QUOTA",
            detail={"active": active, "limit": quota},
        )


async def _ensure_session(
    state: AppState, subject: Subject, agent_id: str, agent_version: int, session_id: str | None
) -> str:
    if session_id:
        return session_id
    sid = f"ses-{uuid.uuid4().hex[:12]}"
    async with state.sessions() as s:
        s.add(
            SessionRow(
                id=sid,
                tenant_id=subject.tenant_id,
                user_id=subject.user_id,
                agent_id=agent_id,
                agent_version=agent_version,
            )
        )
        await s.commit()
    return sid


@router.post("", response_model=RunResult)
async def create_run(
    body: RunCreateRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> RunResult:
    state: AppState = request.app.state.agent
    await _enforce_tenant_quota(state, subject.tenant_id)  # §16.3 租户并发配额
    agent_id, agent_version, system_prompt, default_model, release_status = await _resolve_agent(
        state, subject.tenant_id, body.agent_id, user_id=subject.user_id
    )
    frozen = await _build_frozen(state, subject.tenant_id, agent_id, agent_version, release_status)
    session_id = await _ensure_session(state, subject, agent_id, agent_version, body.session_id)
    run_input = RunInput(
        tenant_id=subject.tenant_id,
        user_id=subject.user_id,
        agent_id=agent_id,
        session_id=session_id,
        text=body.input,
        model=body.model or default_model,
        history=body.history,  # §10 对话多轮上下文
    )
    run_id = uuid.uuid4().hex
    budget = default_budget_from_settings(state.settings)

    if not body.await_result:
        # §9 异步：入队，Worker 处理（优先级 P1）
        await state.job_queue.enqueue(
            tenant_id=subject.tenant_id,
            job_type="agent_run",
            priority=1,
            payload={
                "run_input": run_input.model_dump(),
                "run_id": run_id,
                "agent_version": agent_version,
                "system_prompt": system_prompt,
                "budget": budget.to_dict(),
                "release_status": release_status,
                "frozen_versions": frozen,
            },
        )
        return RunResult(
            run_id=run_id,
            tenant_id=subject.tenant_id,
            user_id=subject.user_id,
            agent_id=agent_id,
            agent_version=agent_version,
            session_id=session_id,
            state="QUEUED",
            steps=0,
        )

    result = await execute_run(
        run_input,
        _deps(state),
        run_id=run_id,
        agent_version=agent_version,
        system_prompt=system_prompt,
        budget=budget,
        release_status=release_status,
        frozen=frozen,
    )
    # §12.4 记忆自动沉淀：run 完成后提炼会话用户事实写入记忆（失败不影响返回）
    await _sediment_memory(state, subject, run_id)
    await persist_chat_messages(state, run_id)  # §10 对话持久化：写入会话消息
    return result


@router.post("/stream")
async def stream_run(
    body: RunCreateRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> StreamingResponse:
    """SSE 流式：run 边执行边推送 tool_call / tool_result / answer 事件。

    事件格式 `data: {json}\n\n`：
      {"type":"tool_call","tool":..,"args":..}  工具即将调用
      {"type":"tool_result","tool":..,"ok":bool} 工具返回
      {"type":"answer","answer":".."}            最终答案
      {"type":"done","run_id":..,"state":..}     完成
      {"type":"error","message":".."}            失败
    """
    state: AppState = request.app.state.agent
    await _enforce_tenant_quota(state, subject.tenant_id)
    agent_id, agent_version, system_prompt, default_model, release_status = await _resolve_agent(
        state, subject.tenant_id, body.agent_id, user_id=subject.user_id
    )
    frozen = await _build_frozen(state, subject.tenant_id, agent_id, agent_version, release_status)
    session_id = await _ensure_session(state, subject, agent_id, agent_version, body.session_id)
    run_input = RunInput(
        tenant_id=subject.tenant_id,
        user_id=subject.user_id,
        agent_id=agent_id,
        session_id=session_id,
        text=body.input,
        model=body.model or default_model,
        history=body.history,
    )
    run_id = uuid.uuid4().hex
    budget = default_budget_from_settings(state.settings)

    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put(event)

    # 先推 start（含 run_id/session_id），供前端「停止生成」与会话绑定
    await queue.put({"type": "start", "run_id": run_id, "session_id": session_id})

    async def run_task() -> None:
        try:
            result = await execute_run(
                run_input,
                _deps(state),
                run_id=run_id,
                agent_version=agent_version,
                system_prompt=system_prompt,
                budget=budget,
                release_status=release_status,
                frozen=frozen,
                emit=emit,
            )
            await _sediment_memory(state, subject, run_id)
            await persist_chat_messages(state, run_id)  # §10 对话持久化
            await queue.put(
                {
                    "type": "done",
                    "run_id": run_id,
                    "session_id": result.session_id,
                    "state": result.state,
                    "answer": result.answer,
                }
            )
        except Exception as exc:  # noqa: BLE001 流式通道不因内部异常中断
            await persist_chat_messages(state, run_id)  # 失败也持久化，避免对话记录丢失
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)

    task = asyncio.create_task(run_task())

    async def sse():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


async def _sediment_memory(state: AppState, subject: Subject, run_id: str) -> None:
    """§12.4 run 结束后提炼会话中的用户事实写入记忆（静默失败，不影响主流程）。

    优先用 checkpoint 里的多轮 messages；无工具步没存 checkpoint 时回落 run 的用户输入。
    """
    try:
        import json

        from app.memory.extract import MemoryExtractor

        run = await state.store.get_run_full(run_id)
        if run is None:
            return
        cp = json.loads(run.get("checkpoint_json") or "{}")
        messages = cp.get("messages") or []
        if not messages:
            input_text = json.loads(run.get("input_json") or "{}").get("text", "")
            messages = [{"role": "user", "content": input_text}] if input_text else []
        if messages:
            await MemoryExtractor(state.gateway, state.memory_service).sediment(subject, messages)
    except Exception:  # noqa: BLE001
        pass


@router.post("", response_model=RunResult)
@router.get("")
async def list_runs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """JSON run 列表（产品化前端 Runs/Dashboard 用，分页 offset/limit）。"""
    state: AppState = request.app.state.agent
    runs = await state.store.list_runs(limit=limit, offset=offset)
    return {"runs": runs, "total": len(runs)}


@router.get("/{run_id}")
async def get_run(run_id: str, request: Request) -> dict:
    state: AppState = request.app.state.agent
    run = await state.store.get_run(run_id)
    if run is None:
        raise AgentError(f"run not found: {run_id}", code="RUN_NOT_FOUND")
    steps = await state.store.list_steps(run_id)
    # §13.3 敏感数据脱敏：观测/排障 API 返回掩码视图（原始数据仅留 DB 供 Replay/续跑）
    return {"run": mask_object(run), "steps": mask_object(steps)}


@router.get("/{run_id}/cost")
async def run_cost(run_id: str, request: Request) -> dict:
    """§50.1 成本归因：该 Run 的 LLM 调用级 CostBreakdown。"""
    state: AppState = request.app.state.agent
    run = await state.store.get_run(run_id)
    if run is None:
        raise AgentError(f"run not found: {run_id}", code="RUN_NOT_FOUND")
    calls = await state.store.list_llm_calls(run_id)
    total = sum(c["estimated_cost"] for c in calls)
    tokens_in = sum(c["tokens_in"] for c in calls)
    tokens_out = sum(c["tokens_out"] for c in calls)
    return {
        "run_id": run_id,
        "tenant_id": run["tenant_id"],
        "user_id": run["user_id"],
        "agent_id": run["agent_id"],
        "agent_version": run["agent_version"],
        "llm_calls": calls,
        "totals": {"estimated_cost": round(total, 6), "tokens_in": tokens_in, "tokens_out": tokens_out},
    }


@router.get("/{run_id}/trace/payloads")
async def run_payloads(run_id: str, request: Request) -> dict:
    """§17.3 Trace payload 采样：查看该 Run 被采样存储的 prompt/输出（脱敏）。"""
    state: AppState = request.app.state.agent
    run = await state.store.get_run(run_id)
    if run is None:
        raise AgentError(f"run not found: {run_id}", code="RUN_NOT_FOUND")
    payloads = await state.payload_recorder.list_for_run(run_id)
    return {"run_id": run_id, "payloads": payloads, "total": len(payloads)}


@router.get("/{run_id}/schedule")
async def run_schedule(run_id: str, request: Request) -> dict:
    """§52 调度决策：该 Run 每次 LLM 调用的调度过滤管线决策（Replay 对比原材料）。"""
    state: AppState = request.app.state.agent
    run = await state.store.get_run(run_id)
    if run is None:
        raise AgentError(f"run not found: {run_id}", code="RUN_NOT_FOUND")
    calls = await state.store.list_llm_calls(run_id)
    return {
        "run_id": run_id,
        "decisions": [
            {"model": c["model"], "step_id": c["step_id"], "scheduler_reason": c["scheduler_reason"]}
            for c in calls
        ],
    }


@router.post("/{run_id}/schedule/compare")
async def compare_schedule(run_id: str, request: Request, body: ReplayRequest | None = None) -> dict:
    """§52 调度决策 Replay 对比：原 run vs 重放 run 的每次调度决策。"""
    state: AppState = request.app.state.agent
    if await state.store.get_run(run_id) is None:
        raise AgentError(f"run not found: {run_id}", code="RUN_NOT_FOUND")
    replay_result = await _replay(state, run_id, body)
    orig = await state.store.list_llm_calls(run_id)
    replay = await state.store.list_llm_calls(replay_result.run_id)
    return {
        "original_run": run_id,
        "replay_run": replay_result.run_id,
        "original_decisions": [
            {"model": c["model"], "scheduler_reason": c["scheduler_reason"]} for c in orig
        ],
        "replay_decisions": [
            {"model": c["model"], "scheduler_reason": c["scheduler_reason"]} for c in replay
        ],
    }


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request) -> dict:
    state: AppState = request.app.state.agent
    run = await state.store.get_run(run_id)
    if run is None:
        raise AgentError(f"run not found: {run_id}", code="RUN_NOT_FOUND")
    if run["finished_at"] is not None:
        return {"run_id": run_id, "cancelled": False, "state": run["state"], "message": "already finished"}
    await state.cancel.cancel(run_id)
    return {"run_id": run_id, "cancelled": True, "message": "cancel requested"}


@router.post("/{run_id}/pause")
async def pause_run(run_id: str, request: Request) -> dict:
    """§10.3 用户暂停：步间协作暂停（checkpoint 已落），resume 续跑。"""
    state: AppState = request.app.state.agent
    run = await state.store.get_run(run_id)
    if run is None:
        raise AgentError(f"run not found: {run_id}", code="RUN_NOT_FOUND")
    if run["finished_at"] is not None:
        return {"run_id": run_id, "paused": False, "state": run["state"], "message": "already finished"}
    await state.cancel.pause(run_id)
    return {"run_id": run_id, "paused": True, "message": "pause requested"}


@router.post("/{run_id}/resume", response_model=RunResult)
async def resume_run_endpoint(run_id: str, request: Request) -> RunResult:
    """§8.4/§10.3 断点续跑：崩溃恢复 / 暂停后续跑。"""
    state: AppState = request.app.state.agent
    await state.cancel.clear_pause(run_id)  # §10.3 resume 即清除暂停标记
    return await resume_run(run_id, _deps(state))


async def _replay(state: AppState, run_id: str, body: ReplayRequest | None) -> RunResult:
    """§60 Replay：原始 input/版本集重放（可换 model/system_prompt/检索 top_k），新 run 标记 replay_of。"""
    orig = await state.store.get_run_full(run_id)
    if orig is None:
        raise AgentError(f"run not found: {run_id}", code="RUN_NOT_FOUND")
    req = RunInput(**json.loads(orig["input_json"]))
    model_config = json.loads(orig["model_config"] or "{}")
    override_model = body.model if body else None
    req.model = override_model or req.model or model_config.get("model")
    override_prompt = body.system_prompt if body and body.system_prompt else None
    system_prompt = override_prompt or model_config.get("system_prompt") or ""
    if body is not None and body.top_k is not None:
        req.retrieval_top_k = body.top_k
    budget = ExecutionBudget(**json.loads(orig["budget_json"] or "{}"))
    new_run_id = uuid.uuid4().hex
    return await execute_run(
        req,
        _deps(state),
        run_id=new_run_id,
        agent_version=orig["agent_version"],
        system_prompt=system_prompt,
        budget=budget,
        replay_of=run_id,
        frozen=model_config.get("frozen_versions") or {},  # §22.1 Replay 沿用冻结版本集
    )


def _diff_answers(a: str | None, b: str | None) -> dict:
    if a == b:
        return {"same": True}
    a_tokens, b_tokens = (a or "").split(), (b or "").split()
    opcodes = difflib.SequenceMatcher(None, a_tokens, b_tokens).get_opcodes()
    removed = [a_tokens[i1:i2] for tag, i1, i2, j1, j2 in opcodes if tag in ("delete", "replace")]
    added = [b_tokens[j1:j2] for tag, i1, i2, j1, j2 in opcodes if tag in ("insert", "replace")]
    return {
        "same": False,
        "removed": " ".join(w for seg in removed for w in seg),
        "added": " ".join(w for seg in added for w in seg),
    }


@router.post("/{run_id}/replay", response_model=RunResult)
async def replay_run(run_id: str, request: Request, body: ReplayRequest | None = None) -> RunResult:
    """§60 Replay：用原始 input/版本集重放（可换 model / system_prompt），新 run 标记 replay_of=原 run。"""
    state: AppState = request.app.state.agent
    return await _replay(state, run_id, body)


@router.post("/{run_id}/compare")
async def compare_run(run_id: str, request: Request, body: ReplayRequest | None = None) -> dict:
    """§60 对比 Replay：重放（可换 model/system_prompt/检索 top_k）并与原 run 的答案/检索参数做 Diff。"""
    state: AppState = request.app.state.agent
    orig = await state.store.get_run_full(run_id)
    if orig is None:
        raise AgentError(f"run not found: {run_id}", code="RUN_NOT_FOUND")
    replay_result = await _replay(state, run_id, body)
    orig_out = json.loads(orig["output_json"] or "{}")
    orig_ans = orig_out.get("answer")
    # §60 换检索：展示 original vs replay 的 top_k
    orig_input = json.loads(orig["input_json"])
    orig_top_k = orig_input.get("retrieval_top_k")
    replay_full = await state.store.get_run_full(replay_result.run_id)
    replay_top_k = (
        json.loads(replay_full["input_json"] or "{}").get("retrieval_top_k") if replay_full else None
    )
    return {
        "original_run": run_id,
        "replay_run": replay_result.run_id,
        "original_answer": orig_ans,
        "replay_answer": replay_result.answer,
        "diff": _diff_answers(orig_ans, replay_result.answer),
        "retrieval": {
            "original_top_k": orig_top_k,
            "replay_top_k": replay_top_k,
            "overridden": replay_top_k is not None and replay_top_k != orig_top_k,
        },
        "overrides": {
            "model": (body.model if body else None),
            "system_prompt": (body.system_prompt if body else None),
            "top_k": (body.top_k if body else None),
        },
    }
