"""Agent Runtime 执行循环（§3.5 / §4） + Checkpoint/Resume（§8）。

职责：状态机推进 + 预算守卫 + 工具编排 + 每步持久化 + 死循环检测 + 检查点续跑。
MVP 取舍：
- 模型重试（指数退避）已实现；模型路由/降级后置（§52）。
- 工具错误（含参数/未找到）作为 observation 回喂 LLM 修正（§11.4），
  权限类错误不回喂（raise 到 FAILED 由调用方处理）。
- 崩溃恢复：检查点持久化 + resume 续跑（LLM 重做、工具幂等至多一次）。
"""

import asyncio
import json
import logging
import random
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from decimal import Decimal

from app.agent.context import builder as ctx
from app.agent.context.summary import apply_context_budget
from app.agent.model.gateway import ModelGateway
from app.agent.runtime.budget import BudgetGuard, BudgetSpent, ExecutionBudget
from app.agent.runtime.cancel import CancellationToken, CancelService
from app.agent.runtime.state import AgentState, StateMachine
from app.agent.runtime.store import RunStore
from app.common.contracts import (
    RETRIEVAL_KNOWLEDGE_VERSION,
    RETRIEVAL_TOP_K,
    RunInput,
    RunResult,
    Subject,
    ToolCallRequest,
)
from app.common.errors import (
    AgentError,
    ApprovalRequiredError,
    LoopDetectedError,
    ModelError,
    ModelRateLimitError,
    ModelTimeoutError,
    RunCancelledError,
    ToolError,
    ToolInvalidArgumentError,
    ToolTimeoutError,
)
from app.observability.otel import span
from app.observability.payloads import TracePayloadRecorder
from app.security.redact import mask_object
from app.storage.lock import RunLockService
from app.tool.registry import ToolRegistry
from app.tool.runtime import ToolRuntime

logger = logging.getLogger(__name__)

LOOP_FINGERPRINT_N = 3  # 连续 N 步同指纹 => 判定死循环


def _token_breakdown(messages: list[dict]) -> dict:
    """§H.1 按角色统计输入 token 分项（prompt/system / history / tool / rag）。"""
    from app.knowledge.embedding import tokenize

    prompt = history = tool = rag = 0
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            prompt += len(tokenize(content))
        elif role == "user":
            history += len(tokenize(content))
        elif role == "assistant":
            if m.get("tool_calls"):
                tool += len(tokenize(json.dumps(m["tool_calls"], ensure_ascii=False)))
            else:
                history += len(tokenize(content))
        elif role == "tool":
            t = len(tokenize(content))
            tool += t
            if '"tool_ref": "kb.search"' in content:  # RAG 结果单列
                rag += t
    return {
        "prompt_tokens": prompt,
        "history_tokens": history,
        "tool_tokens": tool,
        "rag_tokens": rag,
    }


def rebuild_messages_from_run(run: dict, steps: list[dict]) -> list[dict]:
    """§10.4 从 run 元数据 + steps 重建消息序列（与 builder 一致）。

    用于验证「不存 messages 也能从 steps 重建」；实际 resume 仍用已截断的有界 messages。
    """
    from app.agent.context import builder as ctx
    from app.common.contracts import ToolCallDraft

    mc = json.loads(run["model_config"] or "{}")
    inp = json.loads(run["input_json"] or "{}")
    system_prompt = mc.get("system_prompt") or ""
    history = inp.get("history") or []
    user_text = inp.get("text") or ""
    if history:
        messages = (
            [{"role": "system", "content": system_prompt}]
            + list(history)
            + [{"role": "user", "content": user_text}]
        )
    else:
        messages = ctx.build_messages(system_prompt=system_prompt, user_text=user_text)
    for s in sorted(steps, key=lambda x: x["seq"]):
        llm = s.get("llm") or {}
        raw_calls = llm.get("tool_calls") or []
        if raw_calls:
            ctx.append_tool_call_block(messages, [ToolCallDraft(**tc) for tc in raw_calls])
        for i, obs in enumerate(s.get("observations") or []):
            # tool result 的 id 用 LLM 原始 ToolCallDraft.id（与运行时一致），非哈希 call_id
            call_id = raw_calls[i]["id"] if i < len(raw_calls) else obs["call_id"]
            ctx.append_tool_result(messages, call_id, json.dumps(obs, ensure_ascii=False))
    return messages


def call_id_for(run_id: str, tool_ref: str, args_json: str) -> str:
    """确定性幂等键：同 run + 同工具 + 同参数 => 同 call_id（§4.7）。"""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:{tool_ref}:{args_json}").hex


class RuntimeDeps:
    def __init__(
        self,
        *,
        store: RunStore,
        registry: ToolRegistry,
        gateway: ModelGateway,
        lock: RunLockService,
        cancel: CancelService,
        tool_runtime: ToolRuntime,
        payload_recorder: TracePayloadRecorder | None = None,
        memory_service=None,  # §12.4 记忆自动使用（可空，空则不注入）
    ):
        self.store = store
        self.registry = registry
        self.gateway = gateway
        self.lock = lock
        self.cancel = cancel
        self.tool_runtime = tool_runtime
        self.memory_service = memory_service
        self.payload_recorder = payload_recorder


async def _call_llm_with_retry(
    gateway: ModelGateway,
    *,
    messages: list,
    tools: list,
    model: str,
    max_retries: int,
    spent: BudgetSpent,
    token: CancellationToken | None = None,
    tenant_id: str | None = None,
    on_token=None,
):
    """对瞬时性模型错误（超时/限流）指数退避重试（§3.8）；取消在途透传（§8.2）。

    流式（on_token 非空）时不重试：避免已推送的 token 重复。
    """
    attempt = 0
    while True:
        try:
            if on_token is not None:
                return await gateway.stream_complete(
                    messages=messages,
                    tools=tools,
                    model=model,
                    token=token,
                    tenant_id=tenant_id,
                    on_token=on_token,
                )
            return await gateway.complete(
                messages=messages, tools=tools, model=model, token=token, tenant_id=tenant_id
            )
        except (ModelTimeoutError, ModelRateLimitError) as exc:
            if on_token is not None:
                raise  # 流式中途失败不重试
            attempt += 1
            spent.retries += 1
            if attempt > max_retries:
                raise ModelError(f"LLM failed after {attempt} retries: {exc.message}") from exc
            # §9.2 指数退避 + 抖动（防 Retry Storm 同刻重打）
            base = 0.2 * (2**attempt)
            await asyncio.sleep(base + random.uniform(0, 0.05 * (2**attempt)))


async def _execute_one_tool(
    deps: RuntimeDeps,
    *,
    run_id: str,
    subject: Subject,
    tc,
    spent: BudgetSpent,
    token: CancellationToken | None = None,
) -> dict:
    """执行单个工具：解析 → ToolRuntime 全管线（权限/限流/风险/校验/幂等/审计）。
    错误作为 observation 返回；权限类错误不回喂由外层判定（§11.4 备注）。
    """
    started = time.monotonic()
    call_id = "call_failed"
    try:
        args = json.loads(tc.arguments) if tc.arguments else {}
        if not isinstance(args, dict):
            raise ToolInvalidArgumentError("tool arguments must be a JSON object")
        call_id = call_id_for(run_id, tc.name, json.dumps(args, sort_keys=True))
        # tool_calls 表先落 RUNNING 行（审计/幂等基础），执行后落最终状态
        await deps.store.insert_tool_call(
            call_id=call_id,
            run_id=run_id,
            tenant_id=subject.tenant_id,
            user_id=subject.user_id,
            tool_ref=tc.name,
            args_json=json.dumps(args, ensure_ascii=False),
        )
        call = ToolCallRequest(
            call_id=call_id,
            tenant_id=subject.tenant_id,
            user_id=subject.user_id,
            run_id=run_id,
            tool_ref=tc.name,
            args=args,
        )
        async with span("tool.execute", run_id=run_id, tool_ref=tc.name, user_id=subject.user_id):
            res = await deps.tool_runtime.execute(call, token=token)
        latency_ms = int((time.monotonic() - started) * 1000)
        await deps.store.finalize_tool_call(
            call_id=call_id,
            result_json=res.model_dump(exclude_none=True),
            status="SUCCEEDED" if res.ok else "FAILED",
            error_code=(res.error or {}).get("code") if not res.ok else None,
            latency_ms=latency_ms,
        )
        return {
            "tool_ref": tc.name,
            "call_id": call_id,
            "ok": res.ok,
            "data": res.data,
            "latency_ms": latency_ms,
        }
    except ApprovalRequiredError:
        raise  # 审批阻塞：不当作普通工具失败，中断 run 进入 WAITING_APPROVAL（§19）
    except ToolTimeoutError:
        raise  # §3.4 工具超时结果未知：上层收敛到 UNKNOWN，待 reconcile
    except ToolError as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        await deps.store.finalize_tool_call(
            call_id=call_id, result_json={}, status="FAILED", error_code=exc.code, latency_ms=latency_ms
        )
        return {
            "tool_ref": tc.name,
            "call_id": call_id,
            "ok": False,
            "error": exc.to_dict(),
            "latency_ms": latency_ms,
        }


async def _safe_emit(emit: Callable[[dict], Awaitable[None]] | None, event: dict) -> None:
    """流式事件发送：客户端断开等异常不阻断 run 主流程。"""
    if emit is None:
        return
    try:
        await emit(event)
    except Exception:  # noqa: BLE001 流式通道失败仅记日志
        logging.getLogger(__name__).debug("emit failed: %s", event.get("type"))


async def _drive_loop(
    deps: RuntimeDeps,
    *,
    run_id: str,
    sm: StateMachine,
    messages: list,
    spent: BudgetSpent,
    budget: ExecutionBudget,
    model: str,
    subject: Subject,
    start: float,
    session_id: str = "",
    agent_id: str = "",
    emit: Callable[[dict], Awaitable[None]] | None = None,
) -> tuple[str | None, dict | None, AgentState]:
    """核心循环：预算守卫 → 取消检查 → LLM → 工具编排 → 每步检查点。

    返回 (answer, error, terminal)；spent 原地累计。
    """
    store = deps.store
    guard = BudgetGuard(budget)
    answer: str | None = None
    error: dict | None = None
    terminal = AgentState.FAILED
    loop_fp: deque = deque(maxlen=LOOP_FINGERPRINT_N)
    # §8.2 在途取消：watcher 监测 run 取消标志并设置 token，打断在途 LLM/工具调用
    token = CancellationToken()

    async def _watch_cancel() -> None:
        while not token.cancelled:
            if await deps.cancel.is_cancelled(run_id):
                token.cancel()
                return
            await asyncio.sleep(0.05)

    watch = asyncio.create_task(_watch_cancel())

    # §10.4 上下文生命周期分层 + 预算：近轮原文、旧轮摘要、总量受约束（防 Context Overflow）
    messages = await apply_context_budget(messages, max_tokens=4000, keep_recent=5)

    try:
        while True:
            spent.elapsed_s = time.monotonic() - start
            check = guard.check(spent)
            if check.exceeded:
                terminal = AgentState.TIMEOUT
                error = {"code": "BUDGET_EXCEEDED", "message": f"budget exceeded: {check.reason}"}
                sm.transition(AgentState.TIMEOUT, reason=check.reason)
                break
            if await deps.cancel.is_cancelled(run_id) or token.cancelled:
                terminal = AgentState.CANCELLED
                error = {"code": "RUN_CANCELLED", "message": "cancelled by user"}
                sm.transition(AgentState.CANCELLED, reason="user cancel")
                break

            # §10.3 用户暂停：步间检查，已落 checkpoint，resume 从断点续
            if await deps.cancel.is_paused(run_id):
                terminal = AgentState.PAUSED
                sm.transition(AgentState.PAUSED, reason="user pause")
                break

            await deps.lock.touch(run_id)

            step_started = time.monotonic()  # §9.1 分层超时：单步计时
            _llm_start = time.monotonic()
            async with span(
                "llm.call",
                run_id=run_id,
                model=model,
                session_id=session_id,
                agent_id=agent_id,
                user_id=subject.user_id,
                step_id=str(spent.steps),
            ) as sp:
                result = await _call_llm_with_retry(
                    deps.gateway,
                    messages=messages,
                    tools=deps.registry.schemas(),
                    model=model,
                    max_retries=budget.max_retries,
                    spent=spent,
                    token=token,
                    tenant_id=subject.tenant_id,
                    on_token=(
                        lambda t: _safe_emit(emit, {"type": "token", "text": t})  # 流式 token
                    )
                    if emit is not None
                    else None,
                )
                sp.set_attribute("tokens_in", result.tokens_in)
                sp.set_attribute("tokens_out", result.tokens_out)
                sp.set_attribute("cost", float(result.cost))
            # §9.1 单步超时：本步（LLM+编排）超上限 => TIMEOUT（比总 runtime 更早兜底悬挂步）
            if (
                budget.step_timeout_s is not None
                and (time.monotonic() - step_started) > budget.step_timeout_s
            ):
                terminal = AgentState.TIMEOUT
                error = {"code": "AGENT_TIMEOUT", "message": f"step exceeded {budget.step_timeout_s}s"}
                sm.transition(AgentState.TIMEOUT, reason="step timeout")
                break
            # §50.1 成本归因：每次 LLM 调用落一条（随 Run 聚合）+ §52 调度决策
            await store.record_llm_call(
                run_id=run_id,
                step_id=str(spent.steps),
                model=result.model,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                estimated_cost=float(result.cost),
                latency_ms=int((time.monotonic() - _llm_start) * 1000),
                scheduler_reason=deps.gateway.last_schedule_reason,
                **_token_breakdown(messages),  # §H.1 输入 token 分项
            )
            # §17.3 Trace payload 采样存储（脱敏；默认采样率）
            if deps.payload_recorder is not None:
                await deps.payload_recorder.record(
                    trace_id=run_id,
                    run_id=run_id,
                    span_name="llm.call",
                    kind="llm",
                    payload={"messages": mask_object(messages), "model": result.model},
                )
            spent.steps += 1
            spent.tokens_in += result.tokens_in
            spent.tokens_out += result.tokens_out
            spent.cost += float(result.cost)

            if result.tool_calls:
                # §19 预执行检查点：审批阻塞时可从"已决策、未执行"续跑（批准后 resume 幂等放行）
                await store.set_checkpoint(
                    run_id,
                    {
                        "messages": messages,
                        "steps": spent.steps,
                        "tokens_in": spent.tokens_in,
                        "tokens_out": spent.tokens_out,
                        "cost": spent.cost,
                        "tool_calls": spent.tool_calls,
                    },
                )
                sm.transition(AgentState.WAITING_TOOL, reason="tool calls requested")
                await store.set_state(run_id, sm.state.value)
                ctx.append_tool_call_block(messages, result.tool_calls)
                observations = []
                for tc in result.tool_calls:
                    spent.tool_calls += 1
                    await _safe_emit(emit, {"type": "tool_call", "tool": tc.name, "args": tc.arguments})
                    obs = await _execute_one_tool(
                        deps, run_id=run_id, subject=subject, tc=tc, spent=spent, token=token
                    )
                    observations.append(obs)
                    # 检索类工具：带出命中文档 id（对话「引用来源」）
                    docs: list[str] = []
                    data = obs.get("data")
                    if isinstance(data, list):
                        docs = sorted(
                            {
                                c.get("document_id")
                                for c in data
                                if isinstance(c, dict) and c.get("document_id")
                            }
                        )
                    await _safe_emit(
                        emit,
                        {
                            "type": "tool_result",
                            "tool": tc.name,
                            "ok": bool(obs.get("ok")),
                            **({"docs": docs} if docs else {}),
                        },
                    )
                    ctx.append_tool_result(messages, tc.id, json.dumps(obs, ensure_ascii=False))
                sm.transition(AgentState.OBSERVING, reason="tool results ready")
                sm.transition(AgentState.REFLECTING, reason="observed")

                fp = tuple(sorted((tc.name, tc.arguments) for tc in result.tool_calls))
                loop_fp.append(fp)
                if len(loop_fp) == loop_fp.maxlen and len(set(loop_fp)) == 1:
                    raise LoopDetectedError(
                        f"agent stuck: repeated tool-call loop {fp}", code="AGENT_LOOP_DETECTED"
                    )

                await store.add_step(
                    run_id=run_id,
                    seq=spent.steps,
                    state=AgentState.REFLECTING.value,
                    llm_json={
                        "model": result.model,
                        "tool_calls": [tc.model_dump() for tc in result.tool_calls],
                        "tokens_in": result.tokens_in,
                        "tokens_out": result.tokens_out,
                        "cost": float(result.cost),
                    },
                    tool_calls_json=observations,
                    observations_json=observations,
                    decision="continue",
                    tokens_used=result.tokens_in + result.tokens_out,
                    cost=float(result.cost),
                )
                # §8/§10.4 检查点：结构化（current_step/run_state）+ 有界 messages + 预算快照
                await store.set_checkpoint(
                    run_id,
                    {
                        "current_step": spent.steps,
                        "run_state": sm.state.value,
                        "messages": messages,  # 已由 apply_context_budget 截断为有界
                        "steps": spent.steps,
                        "tokens_in": spent.tokens_in,
                        "tokens_out": spent.tokens_out,
                        "cost": spent.cost,
                        "tool_calls": spent.tool_calls,
                    },
                )
                sm.transition(AgentState.RUNNING, reason="continue loop")
                await store.set_state(run_id, sm.state.value)
                continue

            answer = result.content or ""
            await _safe_emit(emit, {"type": "answer", "answer": answer})
            # §17.3 最终输出 payload 采样
            if deps.payload_recorder is not None:
                await deps.payload_recorder.record(
                    trace_id=run_id,
                    run_id=run_id,
                    span_name="llm.output",
                    kind="output",
                    payload={"answer": mask_object(answer), "model": result.model},
                )
            sm.transition(AgentState.REFLECTING, reason="final answer")
            sm.transition(AgentState.COMPLETED, reason="done")
            terminal = AgentState.COMPLETED
            await store.add_step(
                run_id=run_id,
                seq=spent.steps,
                state=AgentState.COMPLETED.value,
                llm_json={
                    "model": result.model,
                    "content": answer,
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "cost": float(result.cost),
                },
                tool_calls_json=[],
                observations_json=[],
                decision="completed",
                tokens_used=result.tokens_in + result.tokens_out,
                cost=float(result.cost),
            )
            break

    except RunCancelledError:
        terminal = AgentState.CANCELLED
        error = {"code": "RUN_CANCELLED", "message": "cancelled while in flight"}
    except ToolTimeoutError:
        # §3.4 工具超时结果未知：收敛到 UNKNOWN（待 reconcile，而非误判 FAILED）
        terminal = AgentState.UNKNOWN
        error = {
            "code": "TOOL_TIMEOUT_UNKNOWN",
            "message": "tool result unknown after timeout, needs reconcile",
        }
        sm.transition(AgentState.UNKNOWN, reason="tool timeout -> unknown")
    except ApprovalRequiredError as exc:
        # §19 审批阻塞：run 进入 WAITING_APPROVAL（非终态），批准后 resume 续跑
        terminal = AgentState.WAITING_APPROVAL
        error = exc.to_dict()
    except AgentError as exc:
        terminal = AgentState.FAILED
        error = exc.to_dict()
    except Exception as exc:  # 兜底：未预期异常也必须可观测（§3.8）
        terminal = AgentState.FAILED
        error = {"code": "INTERNAL_ERROR", "message": str(exc)}
    finally:
        watch.cancel()
        await asyncio.gather(watch, return_exceptions=True)
    return answer, error, terminal


async def _recall_memory_context(deps, subject: Subject, query: str) -> str:
    """召回与当前问题相关的用户记忆，组装为系统提示中的记忆上下文。失败返回空。"""
    if deps.memory_service is None:
        return ""
    try:
        entries = await deps.memory_service.recall(subject, query=query, k=5)
    except Exception:  # noqa: BLE001
        return ""
    picked = [e for e in entries if e.get("score", 0) >= 0.2][:5]
    if not picked:
        # 兜底：无相关命中时注入最近几条记忆，保证"我是谁"这类通用问题也能用到
        try:
            picked = await deps.memory_service.recall(subject, query="", k=3)
        except Exception:  # noqa: BLE001
            picked = []
    return "\n".join(f"- {e['content']}" for e in picked)


async def execute_run(
    request: RunInput,
    deps: RuntimeDeps,
    *,
    run_id: str,
    agent_version: int,
    system_prompt: str,
    budget: ExecutionBudget,
    replay_of: str | None = None,
    release_status: str | None = None,
    frozen: dict | None = None,
    emit: Callable[[dict], Awaitable[None]] | None = None,
) -> RunResult:
    sm = StateMachine()
    store = deps.store
    subject = Subject(tenant_id=request.tenant_id, user_id=request.user_id)
    model = request.model or deps.gateway.default_model
    # §12.4 记忆自动使用：召回相关用户记忆注入系统提示（回答"我是谁"等个性化问题）
    memory_context = await _recall_memory_context(deps, subject, request.text)
    if memory_context:
        system_prompt = f"{system_prompt}\n\n【已知用户记忆】\n{memory_context}"
    frozen = frozen or {}
    kv = frozen.get("knowledge_version")
    # §10 上下文生命周期：携带历史轮次（system + history + 当前 user）
    if request.history:
        messages = (
            [{"role": "system", "content": system_prompt}]
            + list(request.history)
            + [{"role": "user", "content": request.text}]
        )
    else:
        messages = ctx.build_messages(system_prompt=system_prompt, user_text=request.text)
    spent = BudgetSpent()

    await store.create_run(
        run_id=run_id,
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        agent_id=request.agent_id,
        agent_version=agent_version,
        session_id=request.session_id,
        state=sm.state.value,
        budget_json=budget.to_dict(),
        model_config={
            "model": model,
            "system_prompt": system_prompt,
            "release_status": release_status or "ACTIVE",  # §21 灰度决策落 run
            "release_version": agent_version,
            "frozen_versions": frozen,  # §22.1 版本冻结：tool/knowledge 版本集
        },
        input_json=request.model_dump(),
        replay_of=replay_of,
    )

    if not await deps.lock.acquire(run_id):
        error = {"code": "CONCURRENT_EXECUTION", "message": "run already executing elsewhere"}
        await store.finish_run(
            run_id=run_id,
            state="FAILED",
            output_json=None,
            error_json=error,
            tokens_in=0,
            tokens_out=0,
            cost=0.0,
        )
        return _to_result(request, run_id, agent_version, sm.state.value, spent, None, error)

    sm.transition(AgentState.PLANNING, reason="lock acquired")
    sm.transition(AgentState.RUNNING, reason="execution started")
    await store.set_state(run_id, sm.state.value)

    token_ctx = RETRIEVAL_TOP_K.set(request.retrieval_top_k) if request.retrieval_top_k is not None else None
    kv_ctx = RETRIEVAL_KNOWLEDGE_VERSION.set(kv) if kv is not None else None
    try:
        async with span(
            "agent.run",
            run_id=run_id,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            session_id=request.session_id,
            agent_id=request.agent_id,
        ) as sp:
            sp.set_attribute("agent_version", agent_version)
            sp.set_attribute("release_status", release_status or "ACTIVE")  # §21 灰度决策落 Trace
            sp.set_attribute("knowledge_version", kv or "")  # §22.1 冻结版本入 Trace
            answer, error, terminal = await _drive_loop(
                deps,
                run_id=run_id,
                sm=sm,
                messages=messages,
                spent=spent,
                budget=budget,
                model=model,
                subject=subject,
                start=time.monotonic(),
                session_id=request.session_id,
                agent_id=request.agent_id,
                emit=emit,
            )
    finally:
        if token_ctx is not None:
            RETRIEVAL_TOP_K.reset(token_ctx)
        if kv_ctx is not None:
            RETRIEVAL_KNOWLEDGE_VERSION.reset(kv_ctx)
        await deps.lock.release(run_id)
        await store.finish_run(
            run_id=run_id,
            state=terminal.value,
            output_json={"answer": answer} if answer is not None else None,
            error_json=error,
            tokens_in=spent.tokens_in,
            tokens_out=spent.tokens_out,
            cost=round(spent.cost, 6),
        )

    return _to_result(request, run_id, agent_version, terminal.value, spent, answer, error)


async def resume_run(run_id: str, deps: RuntimeDeps) -> RunResult:
    """§8.4 断点续跑：从最后一个检查点重新驱动循环。

    语义：LLM 调用重做；已完成工具按幂等键不重复执行（至多一次）。
    """
    store = deps.store
    run = await store.get_run_full(run_id)
    if run is None:
        raise AgentError(f"run not found: {run_id}", code="RUN_NOT_FOUND")

    # §10.3 resume 即清除暂停标记（暂停后续跑）
    await deps.cancel.clear_pause(run_id)

    # 已成功完成的 run 不重放（§8：resume 面向崩溃/中断/超时的 run）
    if run["state"] == AgentState.COMPLETED.value:
        out = json.loads(run["output_json"]) if run["output_json"] else {}
        err = json.loads(run["error_json"]) if run["error_json"] else None
        return _to_result_from_run(run, run["state"], BudgetSpent(), out.get("answer"), err)

    sm = StateMachine()
    spent = BudgetSpent()
    answer: str | None = None
    error: dict | None = None
    terminal = AgentState.FAILED

    if not await deps.lock.acquire(run_id):
        error = {"code": "CONCURRENT_EXECUTION", "message": "run already executing elsewhere"}
        return _to_result_from_run(run, sm.state.value, spent, None, error)

    kv_ctx = None
    topk_ctx = None
    try:
        if not run["checkpoint_json"]:
            error = {"code": "NO_CHECKPOINT", "message": "run has no checkpoint to resume"}
            terminal = AgentState.FAILED
            return _to_result_from_run(run, terminal.value, spent, None, error)

        cp = json.loads(run["checkpoint_json"])
        if cp.get("current_step") is not None:
            logger.info(
                "resume run %s from current_step=%s state=%s", run_id, cp["current_step"], cp.get("run_state")
            )
        messages = cp["messages"]
        spent = BudgetSpent(
            steps=cp.get("steps", 0),
            tokens_in=cp.get("tokens_in", 0),
            tokens_out=cp.get("tokens_out", 0),
            cost=cp.get("cost", 0.0),
            tool_calls=cp.get("tool_calls", 0),
        )
        budget = ExecutionBudget(**json.loads(run["budget_json"]))
        model_config = json.loads(run["model_config"])
        model = model_config.get("model") or deps.gateway.default_model
        subject = Subject(tenant_id=run["tenant_id"], user_id=run["user_id"])
        # §22.1 版本冻结：续跑恢复冻结的 knowledge_version（不漂移）
        frozen_kv = (model_config.get("frozen_versions") or {}).get("knowledge_version")
        if frozen_kv:
            kv_ctx = RETRIEVAL_KNOWLEDGE_VERSION.set(frozen_kv)
        # §60 Replay 换检索参数：续跑恢复 run 级 retrieval_top_k（否则覆盖丢失）
        input_top_k = json.loads(run["input_json"] or "{}").get("retrieval_top_k")
        if input_top_k is not None:
            topk_ctx = RETRIEVAL_TOP_K.set(input_top_k)

        sm.transition(AgentState.PLANNING, reason="resume: lock acquired")
        sm.transition(AgentState.RUNNING, reason="resume: re-drive from checkpoint")
        await store.set_state(run_id, sm.state.value)

        async with span(
            "agent.run",
            run_id=run_id,
            tenant_id=run["tenant_id"],
            user_id=run["user_id"],
            session_id=run["session_id"],
            agent_id=run["agent_id"],
        ):
            answer, error, terminal = await _drive_loop(
                deps,
                run_id=run_id,
                sm=sm,
                messages=messages,
                spent=spent,
                budget=budget,
                model=model,
                subject=subject,
                start=time.monotonic(),
                session_id=run["session_id"],
                agent_id=run["agent_id"],
            )
    finally:
        if kv_ctx is not None:
            RETRIEVAL_KNOWLEDGE_VERSION.reset(kv_ctx)
        if topk_ctx is not None:
            RETRIEVAL_TOP_K.reset(topk_ctx)
        await deps.lock.release(run_id)
        await store.finish_run(
            run_id=run_id,
            state=terminal.value,
            output_json={"answer": answer} if answer is not None else None,
            error_json=error,
            tokens_in=spent.tokens_in,
            tokens_out=spent.tokens_out,
            cost=round(spent.cost, 6),
        )

    return _to_result_from_run(run, terminal.value, spent, answer, error)


def _to_result(
    request: RunInput,
    run_id: str,
    agent_version: int,
    state: str,
    spent: BudgetSpent,
    answer: str | None,
    error: dict | None,
) -> RunResult:
    return RunResult(
        run_id=run_id,
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        agent_id=request.agent_id,
        agent_version=agent_version,
        session_id=request.session_id,
        state=state,
        answer=answer,
        steps=spent.steps,
        tokens_in=spent.tokens_in,
        tokens_out=spent.tokens_out,
        cost=Decimal(str(round(spent.cost, 6))),
        error=error,
    )


def _to_result_from_run(
    run: dict,
    state: str,
    spent: BudgetSpent,
    answer: str | None,
    error: dict | None,
) -> RunResult:
    return RunResult(
        run_id=run["run_id"],
        tenant_id=run["tenant_id"],
        user_id=run["user_id"],
        agent_id=run["agent_id"],
        agent_version=run["agent_version"],
        session_id=run["session_id"],
        state=state,
        answer=answer,
        steps=spent.steps,
        tokens_in=spent.tokens_in,
        tokens_out=spent.tokens_out,
        cost=Decimal(str(round(spent.cost, 6))),
        error=error,
    )
