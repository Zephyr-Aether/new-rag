"""Run/Step/ToolCall 持久化（§3.6）。MVP 用单机 SQLite/PG，每方法独立短事务。"""

import json
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.security.redact import mask
from app.storage.models import AgentRunRow, AgentStepRow, LLMCallRow, ToolCallRow
from app.tool.registry import IdempotencyStore, ToolResult


def _now() -> datetime:
    return datetime.now(UTC)


class RunStore(IdempotencyStore):
    def __init__(self, sessions):
        self.sessions = sessions

    # ---------- run ----------
    async def create_run(
        self,
        *,
        run_id: str,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        agent_version: int,
        session_id: str,
        state: str,
        budget_json: dict,
        model_config: dict,
        input_json: dict,
        replay_of: str | None = None,
        client_run_id: str | None = None,
    ) -> None:
        async with self.sessions() as s:
            s.add(
                AgentRunRow(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    agent_version=agent_version,
                    session_id=session_id,
                    state=state,
                    budget_json=json.dumps(budget_json),
                    model_config=json.dumps(model_config),
                    input_json=json.dumps(input_json),
                    replay_of=replay_of,
                    client_run_id=client_run_id,
                )
            )
            await s.commit()

    async def get_run_by_client_id(self, tenant_id: str, client_run_id: str) -> dict | None:
        """幂等查询：按租户 + 客户端 key 取已提交的 run（§32.5）。"""
        async with self.sessions() as s:
            row = await s.scalar(
                select(AgentRunRow)
                .where(
                    AgentRunRow.tenant_id == tenant_id,
                    AgentRunRow.client_run_id == client_run_id,
                )
                .order_by(AgentRunRow.started_at.desc())
            )
            if row is None:
                return None
            return {
                "run_id": row.run_id,
                "tenant_id": row.tenant_id,
                "user_id": row.user_id,
                "agent_id": row.agent_id,
                "agent_version": row.agent_version,
                "session_id": row.session_id,
                "state": row.state,
                "cost": row.cost,
                "tokens_in": row.tokens_in,
                "tokens_out": row.tokens_out,
                "input_json": row.input_json,
                "output_json": row.output_json,
                "error_json": row.error_json,
                "replay_of": row.replay_of,
                "finished_at": row.finished_at,
            }

    async def get_run(self, run_id: str) -> dict | None:
        async with self.sessions() as s:
            row = await s.get(AgentRunRow, run_id)
            if row is None:
                return None
            return {
                "run_id": row.run_id,
                "tenant_id": row.tenant_id,
                "user_id": row.user_id,
                "agent_id": row.agent_id,
                "agent_version": row.agent_version,
                "session_id": row.session_id,
                "state": row.state,
                "cost": row.cost,
                "tokens_in": row.tokens_in,
                "tokens_out": row.tokens_out,
                "input_json": row.input_json,
                "output_json": row.output_json,
                "error_json": row.error_json,
                "replay_of": row.replay_of,
                "finished_at": row.finished_at,
            }

    async def set_state(self, run_id: str, state: str) -> None:
        """原子写状态 + 版本自增（§3.3 CAS 基础：单条 UPDATE 消除读改写竞态）。"""
        async with self.sessions() as s:
            await s.execute(
                update(AgentRunRow)
                .where(AgentRunRow.run_id == run_id)
                .values(state=state, version=AgentRunRow.version + 1, updated_at=_now())
            )
            await s.commit()

    async def set_state_cas(self, run_id: str, state: str, expected_version: int) -> bool:
        """§3.3/§10.5 乐观锁 CAS：仅当版本匹配才更新，否则返回 False（并发冲突）。"""
        async with self.sessions() as s:
            result = await s.execute(
                update(AgentRunRow)
                .where(AgentRunRow.run_id == run_id, AgentRunRow.version == expected_version)
                .values(state=state, version=expected_version + 1, updated_at=_now())
            )
            await s.commit()
            return result.rowcount > 0

    async def count_active_runs(self, tenant_id: str) -> int:
        """§16.3 租户配额：并发 run 数（执行中/等待工具/等待审批）。"""
        active = {"PLANNING", "RUNNING", "WAITING_TOOL", "WAITING_APPROVAL"}
        async with self.sessions() as s:
            rows = await s.scalars(select(AgentRunRow.state).where(AgentRunRow.tenant_id == tenant_id))
        return sum(1 for st in rows if st in active)

    async def list_runs(self, limit: int = 100, offset: int = 0, state: str | None = None) -> list[dict]:
        """§18 运行列表（调试 Console；分页 offset/limit，可选 state 过滤）。"""
        async with self.sessions() as s:
            q = select(AgentRunRow).order_by(AgentRunRow.started_at.desc())
            if state:
                q = q.where(AgentRunRow.state == state)
            rows = await s.scalars(q.offset(offset).limit(limit))
            return [
                {
                    "run_id": r.run_id,
                    "state": r.state,
                    "cost": r.cost,
                    "tokens_in": r.tokens_in,
                    "tokens_out": r.tokens_out,
                    "agent_version": r.agent_version,
                    "finished_at": r.finished_at,
                    "started_at": r.started_at,
                    "input": mask(json.loads(r.input_json or "{}").get("text", "")),
                }
                for r in rows
            ]

    async def count_runs(self, state: str | None = None) -> int:
        """运行总数（可选 state 过滤），供列表分页计算总页数。"""
        async with self.sessions() as s:
            q = select(AgentRunRow.run_id)
            if state:
                q = q.where(AgentRunRow.state == state)
            return len((await s.scalars(q)).all())

    async def find_run_by_tool_call(self, call_id: str) -> str | None:
        """由工具调用 id 反查 run（§19 审批批准后定位被阻塞的 run）。"""
        async with self.sessions() as s:
            row = await s.get(ToolCallRow, call_id)
            return row.run_id if row else None

    async def touch_lock(self, run_id: str, expires_at: datetime) -> None:
        async with self.sessions() as s:
            row = await s.get(AgentRunRow, run_id)
            if row:
                row.lock_expires_at = expires_at
                row.updated_at = _now()
                await s.commit()

    async def record_llm_call(
        self,
        *,
        run_id: str,
        step_id: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        estimated_cost: float,
        latency_ms: int,
        scheduler_reason: str = "",
        prompt_tokens: int = 0,
        history_tokens: int = 0,
        tool_tokens: int = 0,
        rag_tokens: int = 0,
    ) -> None:
        """§50.1/§H.1 成本归因：每次 LLM 调用落一条（含 prompt/history/tool/rag 分项）。"""
        import uuid

        async with self.sessions() as s:
            run = await s.get(AgentRunRow, run_id)
            s.add(
                LLMCallRow(
                    id=uuid.uuid4().hex,
                    run_id=run_id,
                    step_id=step_id,
                    tenant_id=run.tenant_id if run else "",
                    user_id=run.user_id if run else "",
                    agent_id=run.agent_id if run else "",
                    agent_version=run.agent_version if run else 0,
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    estimated_cost=estimated_cost,
                    latency_ms=latency_ms,
                    scheduler_reason=scheduler_reason,  # §52 调度决策（Replay 对比）
                    prompt_tokens=prompt_tokens,
                    history_tokens=history_tokens,
                    tool_tokens=tool_tokens,
                    rag_tokens=rag_tokens,
                )
            )
            await s.commit()

    async def list_llm_calls(self, run_id: str) -> list[dict]:
        async with self.sessions() as s:
            rows = await s.scalars(select(LLMCallRow).where(LLMCallRow.run_id == run_id))
            return [
                {
                    "model": r.model,
                    "step_id": r.step_id,
                    "tokens_in": r.tokens_in,
                    "tokens_out": r.tokens_out,
                    "cached_input_tokens": r.cached_input_tokens,
                    "reasoning_tokens": r.reasoning_tokens,
                    "prompt_tokens": r.prompt_tokens,
                    "history_tokens": r.history_tokens,
                    "tool_tokens": r.tool_tokens,
                    "rag_tokens": r.rag_tokens,
                    "estimated_cost": r.estimated_cost,
                    "actual_cost": r.actual_cost,
                    "latency_ms": r.latency_ms,
                    "scheduler_reason": r.scheduler_reason,
                }
                for r in rows
            ]

    async def set_checkpoint(self, run_id: str, checkpoint: dict) -> None:
        """§8 检查点：每步后落 messages + 预算快照，供崩溃后续跑。"""
        async with self.sessions() as s:
            row = await s.get(AgentRunRow, run_id)
            if row:
                row.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)
                row.updated_at = _now()
                await s.commit()

    async def get_run_full(self, run_id: str) -> dict | None:
        """取续跑所需的全部字段（§10.4 resume）。"""
        async with self.sessions() as s:
            row = await s.get(AgentRunRow, run_id)
            if row is None:
                return None
            return {
                "run_id": row.run_id,
                "tenant_id": row.tenant_id,
                "user_id": row.user_id,
                "agent_id": row.agent_id,
                "agent_version": row.agent_version,
                "session_id": row.session_id,
                "state": row.state,
                "budget_json": row.budget_json,
                "model_config": row.model_config,
                "input_json": row.input_json,
                "checkpoint_json": row.checkpoint_json,
                "replay_of": row.replay_of,
                "version": row.version,
                "cost": row.cost,
                "tokens_in": row.tokens_in,
                "tokens_out": row.tokens_out,
                "output_json": row.output_json,
                "error_json": row.error_json,
                "finished_at": row.finished_at,
            }

    async def finish_run(
        self,
        *,
        run_id: str,
        state: str,
        output_json: dict | None,
        error_json: dict | None,
        tokens_in: int,
        tokens_out: int,
        cost: float,
    ) -> None:
        async with self.sessions() as s:
            row = await s.get(AgentRunRow, run_id)
            if row is None:
                return
            row.state = state
            row.output_json = json.dumps(output_json) if output_json is not None else None
            row.error_json = json.dumps(error_json) if error_json else None
            row.tokens_in = tokens_in
            row.tokens_out = tokens_out
            row.cost = cost
            row.finished_at = _now()
            row.updated_at = _now()
            await s.commit()

    async def list_runs_in_states(self, states: list[str]) -> list[dict]:
        async with self.sessions() as s:
            rows = await s.scalars(select(AgentRunRow).where(AgentRunRow.state.in_(states)))
            return [
                {"run_id": r.run_id, "lock_expires_at": r.lock_expires_at, "state": r.state} for r in rows
            ]

    # ---------- steps ----------
    async def add_step(
        self,
        *,
        run_id: str,
        seq: int,
        state: str,
        llm_json: dict,
        tool_calls_json: list,
        observations_json: list,
        decision: str,
        tokens_used: int,
        cost: float,
    ) -> None:
        async with self.sessions() as s:
            s.add(
                AgentStepRow(
                    run_id=run_id,
                    seq=seq,
                    state=state,
                    llm_json=json.dumps(llm_json),
                    tool_calls_json=json.dumps(tool_calls_json),
                    observations_json=json.dumps(observations_json),
                    decision=decision,
                    tokens_used=tokens_used,
                    cost=cost,
                )
            )
            await s.commit()

    async def list_steps(self, run_id: str) -> list[dict]:
        async with self.sessions() as s:
            rows = await s.scalars(
                select(AgentStepRow).where(AgentStepRow.run_id == run_id).order_by(AgentStepRow.seq)
            )
            return [
                {
                    "seq": r.seq,
                    "state": r.state,
                    "llm": json.loads(r.llm_json),
                    "tool_calls": json.loads(r.tool_calls_json),
                    "observations": json.loads(r.observations_json),
                    "decision": r.decision,
                    "tokens_used": r.tokens_used,
                    "cost": r.cost,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    # ---------- tool call 幂等（IdempotencyStore 实现） ----------
    async def get(self, call_id: str) -> ToolResult | None:
        async with self.sessions() as s:
            row = await s.get(ToolCallRow, call_id)
            if row is None or row.result_json is None:
                return None
            payload = json.loads(row.result_json)
            return ToolResult(
                ok=payload.get("ok", False), data=payload.get("data"), error=payload.get("error")
            )

    async def set(self, call_id: str, result: ToolResult) -> None:
        async with self.sessions() as s:
            row = await s.get(ToolCallRow, call_id)
            payload = result.to_dict()
            if row is None:
                s.add(
                    ToolCallRow(
                        call_id=call_id,
                        run_id="",
                        tenant_id="",
                        user_id="",
                        tool_ref="",
                        args_json="{}",
                        result_json=json.dumps(payload),
                        status="SUCCEEDED" if result.ok else "FAILED",
                    )
                )
            else:
                row.result_json = json.dumps(payload)
                row.status = "SUCCEEDED" if result.ok else "FAILED"
                row.updated_at = _now()
            await s.commit()

    async def insert_tool_call(
        self,
        *,
        call_id: str,
        run_id: str,
        tenant_id: str,
        user_id: str,
        tool_ref: str,
        args_json: str,
        status: str = "RUNNING",
    ) -> None:
        async with self.sessions() as s:
            row = await s.get(ToolCallRow, call_id)
            if row is None:
                s.add(
                    ToolCallRow(
                        call_id=call_id,
                        run_id=run_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        tool_ref=tool_ref,
                        args_json=args_json,
                        status=status,
                    )
                )
                await s.commit()

    async def finalize_tool_call(
        self,
        *,
        call_id: str,
        result_json: dict,
        status: str,
        error_code: str | None,
        latency_ms: int,
    ) -> None:
        async with self.sessions() as s:
            row = await s.get(ToolCallRow, call_id)
            if row is None:
                return
            row.result_json = json.dumps(result_json)
            row.status = status
            row.error_code = error_code
            row.latency_ms = latency_ms
            row.updated_at = _now()
            await s.commit()
