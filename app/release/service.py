"""ReleaseService（§21）：建版本 / 发布 / 灰度（百分比 + 用户哈希）/ 回滚 / resolve。

- create_version：版本只增不改，创建新 DRAFT 行（version 自增）。
- publish：先过 §58 Release Contract 门禁（fail 阻断），通过后置 ACTIVE。
- contract_check：§58 发布前 10 项兼容性检查，出报告（fail 阻断 / warn 人工签核）。
- gray：目标版本置 GRAY，config_json 存 gray_percentage。
- rollback：切回某版本为 ACTIVE。
- resolve：按 tenant+agent 解析当前生效版本（灰度命中则返回灰度版）。
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text

from app.common.errors import AgentError
from app.queue.schema import migrate_agent_run_payload
from app.storage.models import AgentRow, AgentVersionRow, EventRow, ToolCallRow


def _stable_hash(user_id: str) -> int:
    return int(hashlib.md5(user_id.encode()).hexdigest(), 16)


# §58 Release Contract：10 项检查（报告顺序即此表顺序）
_CONTRACT_CHECK_SPEC: list[tuple[str, str]] = [
    ("api", "API Compatibility"),
    ("queue", "Queue Compatibility"),
    ("db", "DB Compatibility"),
    ("prompt", "Prompt Compatibility"),
    ("tool", "Tool Compatibility"),
    ("model", "Model Compatibility"),
    ("config", "Config Compatibility"),
    ("memory", "Memory Compatibility"),
    ("trace", "Trace Compatibility"),
    ("rollback", "Rollback Compatibility"),
]


class ReleaseService:
    def __init__(self, sessions, *, registry=None, settings=None):
        self.sessions = sessions
        self.registry = registry
        self.settings = settings

    async def _get_version(self, tenant_id: str, agent_id: str, version: int) -> AgentVersionRow:
        async with self.sessions() as s:
            row = await s.scalar(
                select(AgentVersionRow).where(
                    AgentVersionRow.tenant_id == tenant_id,
                    AgentVersionRow.agent_id == agent_id,
                    AgentVersionRow.version == version,
                )
            )
        if row is None:
            raise AgentError(
                f"agent version not found: {agent_id} v{version}", code="AGENT_VERSION_NOT_FOUND"
            )
        return row

    async def create_version(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        system_prompt: str,
        model: str = "",
        config: dict | None = None,
    ) -> dict:
        """§22 版本只增不改：创建新 DRAFT 版本（version 自增，配置走新行）。"""
        async with self.sessions() as s:
            agent = await s.scalar(
                select(AgentRow).where(AgentRow.id == agent_id, AgentRow.tenant_id == tenant_id)
            )
            if agent is None:
                raise AgentError(f"agent not found: {agent_id}", code="AGENT_NOT_FOUND")
            latest = await s.scalar(
                select(AgentVersionRow.version)
                .where(
                    AgentVersionRow.tenant_id == tenant_id,
                    AgentVersionRow.agent_id == agent_id,
                )
                .order_by(AgentVersionRow.version.desc())
                .limit(1)
            )
            version = (latest or 0) + 1
            s.add(
                AgentVersionRow(
                    id=uuid.uuid4().hex,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    version=version,
                    status="DRAFT",
                    system_prompt=system_prompt,
                    model=model,
                    config_json=json.dumps(config or {}, ensure_ascii=False),
                )
            )
            await s.commit()
        return {"agent_id": agent_id, "version": version, "status": "DRAFT"}

    async def list_versions(self, *, tenant_id: str, agent_id: str) -> list[dict]:
        """列出全部版本（按 version 降序）。"""
        async with self.sessions() as s:
            rows = (
                await s.scalars(
                    select(AgentVersionRow)
                    .where(
                        AgentVersionRow.tenant_id == tenant_id,
                        AgentVersionRow.agent_id == agent_id,
                    )
                    .order_by(AgentVersionRow.version.desc())
                )
            ).all()
        return [
            {
                "version": row.version,
                "status": row.status,
                "system_prompt": row.system_prompt,
                "model": row.model,
                "config": json.loads(row.config_json or "{}"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    async def contract_check(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        version: int,
        min_runs: int = 10,
        error_threshold: float = 0.2,
    ) -> dict:
        """§58 发布前 10 项兼容性检查，出报告。

        每条 pass / warn / fail：warn = 平台级或需人工签核（CI + 人工 checklist 双保险），
        不阻断；fail = 阻断发布（publish 门禁据此抛 RELEASE_CONTRACT_FAILED）。
        """
        target = await self._get_version(tenant_id, agent_id, version)
        target_cfg = json.loads(target.config_json or "{}")
        target_tools = set(target_cfg.get("tools", []))
        # 上一生效版本：ACTIVE/GRAY 的最高版本（跳过目标自身）
        async with self.sessions() as s:
            prev = await s.scalar(
                select(AgentVersionRow)
                .where(
                    AgentVersionRow.tenant_id == tenant_id,
                    AgentVersionRow.agent_id == agent_id,
                    AgentVersionRow.status.in_(["ACTIVE", "GRAY"]),
                    AgentVersionRow.version != version,
                )
                .order_by(AgentVersionRow.version.desc())
            )
        prev_cfg = json.loads(prev.config_json or "{}") if prev else {}
        prev_tools = set(prev_cfg.get("tools", []))

        result: dict[str, tuple[str, str]] = {}

        # 1 API：新版本工具集 ⊇ 上一生效版本（"对外 API 面"不意外下架）
        removed = prev_tools - target_tools
        result["api"] = (
            ("fail", f"已声明工具被移除: {sorted(removed)}")
            if removed
            else ("pass", f"工具集 {sorted(target_tools)} 未移除任何已声明工具")
        )

        # 2 Queue：平台级消息迁移可解析（防回归）
        try:
            migrate_agent_run_payload({"run_input": {}, "run_id": "x"})
            result["queue"] = ("pass", "队列消息 schema v1 向后兼容（migrate 幂等）")
        except Exception as exc:  # noqa: BLE001
            result["queue"] = ("fail", f"队列消息迁移失败: {exc}")

        # 3 DB：平台级，MVP 无版本 DDL
        result["db"] = ("warn", "需人工确认 schema 迁移（Expand→Migrate→Contract）；MVP 无版本 DDL")

        # 4 Prompt：近 N run 错误率作质量代理（设计"阻断或降级为灰度"，故 warn 不硬阻断）
        async with self.sessions() as s:
            rows = await s.execute(
                text(
                    "SELECT error_json FROM agent_runs "
                    "WHERE agent_id = :a AND tenant_id = :t ORDER BY started_at DESC LIMIT :n"
                ),
                {"a": agent_id, "t": tenant_id, "n": min_runs},
            )
            recent = [dict(r._mapping) for r in rows]
        n = len(recent)
        rate = sum(1 for r in recent if r["error_json"]) / n if n else 0.0
        if n == 0:
            result["prompt"] = ("warn", "无质量证据（近 0 run），建议先灰度放量")
        elif rate > error_threshold:
            result["prompt"] = ("warn", f"近 {n} run 错误率 {rate:.3f} 偏高，建议灰度观察/修复")
        else:
            result["prompt"] = ("pass", f"近 {n} run 错误率 {rate:.3f} 健康")

        # 5 Tool：声明的工具须已注册
        if self.registry is None:
            result["tool"] = ("n/a", "未注入工具注册表（跳过存在性校验）")
        else:
            known = {t.ref for t in self.registry.list()}
            missing = target_tools - known
            result["tool"] = (
                ("fail", f"声明的工具未注册: {sorted(missing)}")
                if missing
                else ("pass", f"声明的 {len(target_tools)} 个工具均已注册")
            )

        # 6 Model：指定模型须在配置模型集内（空 model 回落默认）
        if target.model:
            if self.settings is None:
                result["model"] = ("n/a", "未注入 settings（跳过模型校验）")
            else:
                allowed = {
                    m
                    for m in [
                        self.settings.llm_model,
                        self.settings.llm_model_small,
                        self.settings.llm_model_medium,
                        self.settings.llm_model_large,
                    ]
                    if m
                }
                result["model"] = (
                    ("pass", f"模型 {target.model} 已配置")
                    if target.model in allowed
                    else ("fail", f"模型 {target.model} 未配置（可选: {sorted(allowed) or '默认'}）")
                )
        else:
            result["model"] = ("pass", "未指定模型，运行时回落默认")

        # 7 Config：配置只增不改（§22），键被移除会破坏回滚
        removed_keys = set(prev_cfg) - set(target_cfg)
        result["config"] = (
            ("fail", f"配置键被移除（破坏回滚）: {sorted(removed_keys)}")
            if removed_keys
            else ("pass", "配置键只增不改（§22）")
        )

        # 8 Memory / 9 Trace：平台级
        result["memory"] = ("warn", "需人工确认记忆读写兼容；MVP 无版本格式差异")
        result["trace"] = ("warn", "需人工确认 Trace 属性向后兼容；MVP 无版本差异")

        # 10 Rollback：非首次发布须有低版本可回滚
        if version == 1:
            result["rollback"] = ("pass", "首次发布，无历史可回滚")
        else:
            async with self.sessions() as s:
                lower = await s.scalar(
                    select(AgentVersionRow.version)
                    .where(
                        AgentVersionRow.tenant_id == tenant_id,
                        AgentVersionRow.agent_id == agent_id,
                        AgentVersionRow.version < version,
                    )
                    .limit(1)
                )
            result["rollback"] = (
                ("pass", f"可回滚到 v{lower}")
                if lower is not None
                else ("fail", f"v{version} 无低版本可回滚")
            )

        checks = [
            {"id": cid, "name": name, "status": result[cid][0], "reason": result[cid][1]}
            for cid, name in _CONTRACT_CHECK_SPEC
        ]
        statuses = {c["status"] for c in checks}
        status = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
        return {
            "agent_id": agent_id,
            "version": version,
            "status": status,
            "blocked": status == "fail",
            "checks": checks,
            "needs_manual": [c["name"] for c in checks if c["status"] == "warn"],
        }

    async def publish(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        version: int,
        enforce_contract: bool = True,
        force: bool = False,
    ) -> dict:
        """发布为 ACTIVE：先过 §58 Release Contract 门禁（fail 阻断），其余 ACTIVE 降为 DISABLED。"""
        if enforce_contract and not force:
            report = await self.contract_check(tenant_id=tenant_id, agent_id=agent_id, version=version)
            if report["status"] == "fail":
                failures = [c for c in report["checks"] if c["status"] == "fail"]
                raise AgentError(
                    "release contract failed, publishing blocked",
                    code="RELEASE_CONTRACT_FAILED",
                    detail={"version": version, "failures": failures},
                )
        async with self.sessions() as s:
            row = await s.scalar(
                select(AgentVersionRow).where(
                    AgentVersionRow.tenant_id == tenant_id,
                    AgentVersionRow.agent_id == agent_id,
                    AgentVersionRow.version == version,
                )
            )
            if row is None:
                raise AgentError(
                    f"agent version not found: {agent_id} v{version}", code="AGENT_VERSION_NOT_FOUND"
                )
            others = await s.scalars(
                select(AgentVersionRow).where(
                    AgentVersionRow.tenant_id == tenant_id,
                    AgentVersionRow.agent_id == agent_id,
                    AgentVersionRow.status == "ACTIVE",
                )
            )
            for o in others:
                if o.version != version:
                    o.status = "DISABLED"
            row.status = "ACTIVE"
            await s.commit()
        return {"agent_id": agent_id, "version": version, "status": "ACTIVE"}

    async def gray(self, *, tenant_id: str, agent_id: str, version: int, percentage: int) -> dict:
        if not 0 <= percentage <= 100:
            raise AgentError("gray percentage must be 0..100", code="INVALID_GRAY_PERCENTAGE")
        row = await self._get_version(tenant_id, agent_id, version)
        cfg = json.loads(row.config_json or "{}")
        cfg["gray_percentage"] = percentage
        async with self.sessions() as s:
            r = await s.get(AgentVersionRow, row.id)
            r.status = "GRAY"
            r.config_json = json.dumps(cfg)
            await s.commit()
        return {"agent_id": agent_id, "version": version, "status": "GRAY", "percentage": percentage}

    async def rollback(self, *, tenant_id: str, agent_id: str, to_version: int | None = None) -> dict:
        """回滚到指定版本（缺省回滚到上一 ACTIVE 版本）。"""
        async with self.sessions() as s:
            current = await s.scalar(
                select(AgentVersionRow)
                .where(
                    AgentVersionRow.tenant_id == tenant_id,
                    AgentVersionRow.agent_id == agent_id,
                    AgentVersionRow.status.in_(["ACTIVE", "GRAY"]),
                )
                .order_by(AgentVersionRow.version.desc())
            )
            target = to_version or (current.version - 1 if current and current.version > 1 else 1)
            row = await s.scalar(
                select(AgentVersionRow).where(
                    AgentVersionRow.tenant_id == tenant_id,
                    AgentVersionRow.agent_id == agent_id,
                    AgentVersionRow.version == target,
                )
            )
            if row is None:
                raise AgentError(f"no version to rollback to: {target}", code="ROLLBACK_FAILED")
            if current:
                current.status = "DISABLED"
            row.status = "ACTIVE"
            await s.commit()
        return {"agent_id": agent_id, "version": target, "status": "ACTIVE"}

    async def halt(self, *, tenant_id: str, agent_id: str, version: int) -> dict:
        """§57 Canary 自动停：把灰度版本 DISABLED（新流量回落 ACTIVE）。"""
        async with self.sessions() as s:
            row = await s.scalar(
                select(AgentVersionRow).where(
                    AgentVersionRow.tenant_id == tenant_id,
                    AgentVersionRow.agent_id == agent_id,
                    AgentVersionRow.version == version,
                )
            )
            if row is None:
                raise AgentError(
                    f"agent version not found: {agent_id} v{version}", code="AGENT_VERSION_NOT_FOUND"
                )
            row.status = "DISABLED"
            await s.commit()
        return {"agent_id": agent_id, "version": version, "status": "DISABLED"}

    async def canary_check(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        version: int,
        min_runs: int = 5,
        error_threshold: float = 0.1,
        cost_budget: float = 1.0,
        latency_threshold_s: float = 30.0,
        tool_success_threshold: float = 0.9,
        rag_recall_threshold: float = 0.3,
        llm_429_threshold: float = 0.2,
        feedback_threshold: int = 3,
        auto_rollback: bool = True,
    ) -> dict:
        """§57 Canary 自动停发布（指标驱动）：Error/Latency/Cost/Tool Success/RAG Recall 任一恶化即停。

        指标来自灰度 run（release_status=GRAY + release_version=version）与其 tool_calls。
        rag_recall 为 kb.search 命中率代理（结果 data 列表非空的比例）。
        """
        async with self.sessions() as s:
            rows = await s.execute(
                text(
                    "SELECT run_id, model_config, error_json, cost, started_at, finished_at, "
                    "tokens_in, tokens_out FROM agent_runs "
                    "WHERE agent_id = :a AND tenant_id = :t"
                ),
                {"a": agent_id, "t": tenant_id},
            )
            runs = [dict(r._mapping) for r in rows]
        gray = []
        for r in runs:
            mc = json.loads(r["model_config"] or "{}")
            if mc.get("release_status") == "GRAY" and mc.get("release_version") == version:
                gray.append(r)
        n = len(gray)
        errors = sum(1 for r in gray if r["error_json"])
        error_rate = errors / n if n else 0.0
        avg_cost = sum(r["cost"] or 0 for r in gray) / n if n else 0.0
        latencies = []
        for r in gray:
            if r["started_at"] and r["finished_at"]:
                # text() 查询返回字符串，需解析；SQLite 存储 aware/naive 混杂，统一转 naive UTC
                try:
                    start = datetime.fromisoformat(r["started_at"])
                    end = datetime.fromisoformat(r["finished_at"])
                except ValueError:
                    continue
                start = start.astimezone(UTC).replace(tzinfo=None) if start.tzinfo else start
                end = end.astimezone(UTC).replace(tzinfo=None) if end.tzinfo else end
                latencies.append((end - start).total_seconds())
        avg_latency_s = sum(latencies) / len(latencies) if latencies else 0.0
        p95_latency_s = (
            sorted(latencies)[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else 0.0
        )
        tokens_in = sum(r["tokens_in"] or 0 for r in gray)
        tokens_out = sum(r["tokens_out"] or 0 for r in gray)

        tool_success_rate: float | None = None
        rag_recall: float | None = None
        llm_429_rate = 0.0
        negative_feedback = 0
        if gray:
            gray_run_ids = [r["run_id"] for r in gray]
            llm_429 = sum(
                1 for r in gray if json.loads(r["error_json"] or "{}").get("code") == "MODEL_RATE_LIMIT"
            )
            llm_429_rate = llm_429 / n if n else 0.0
            async with self.sessions() as s:
                fb = await s.scalar(
                    select(func.count(EventRow.id)).where(
                        EventRow.event_type == "feedback.bad",
                        EventRow.aggregate_id.in_(gray_run_ids),
                    )
                )
            negative_feedback = fb or 0
            async with self.sessions() as s:
                tool_rows = (
                    await s.scalars(select(ToolCallRow).where(ToolCallRow.run_id.in_(gray_run_ids)))
                ).all()
            if tool_rows:
                ok = sum(1 for t in tool_rows if t.status == "SUCCEEDED")
                tool_success_rate = ok / len(tool_rows)
                kb = [t for t in tool_rows if t.tool_ref == "kb.search"]
                if kb:
                    hits = 0
                    for t in kb:
                        try:
                            payload = json.loads(t.result_json or "{}")
                        except (TypeError, json.JSONDecodeError):
                            payload = {}
                        data = payload.get("data")
                        if isinstance(data, list) and data:
                            hits += 1
                    rag_recall = hits / len(kb)

        reasons = [
            f"runs={n}",
            f"error_rate={error_rate:.3f}",
            f"avg_cost={avg_cost:.3f}",
            f"avg_latency_s={avg_latency_s:.2f}",
            f"tool_success={tool_success_rate:.3f}" if tool_success_rate is not None else "tool_success=n/a",
            f"rag_recall={rag_recall:.3f}" if rag_recall is not None else "rag_recall=n/a",
            f"llm_429={llm_429_rate:.3f}",
            f"feedback={negative_feedback}",
        ]
        metrics = {
            "runs": n,
            "error_rate": round(error_rate, 4),
            "avg_cost": round(avg_cost, 4),
            "avg_latency_s": round(avg_latency_s, 3),
            "p95_latency_s": round(p95_latency_s, 3),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tool_success_rate": tool_success_rate,
            "rag_recall": rag_recall,
            "llm_429_rate": round(llm_429_rate, 4),
            "negative_feedback": negative_feedback,
        }
        degraded = bool(
            error_rate > error_threshold
            or avg_cost > cost_budget
            or avg_latency_s > latency_threshold_s
            or (tool_success_rate is not None and tool_success_rate < tool_success_threshold)
            or (rag_recall is not None and rag_recall < rag_recall_threshold)
            or llm_429_rate > llm_429_threshold
            or negative_feedback >= feedback_threshold
        )
        if n >= min_runs and degraded:
            await self.halt(tenant_id=tenant_id, agent_id=agent_id, version=version)
            rolled_back = None
            if auto_rollback:
                # 回滚到被 halt 版本之前的 ACTIVE
                async with self.sessions() as s:
                    prev = await s.scalar(
                        select(AgentVersionRow)
                        .where(
                            AgentVersionRow.tenant_id == tenant_id,
                            AgentVersionRow.agent_id == agent_id,
                            AgentVersionRow.status == "ACTIVE",
                            AgentVersionRow.version < version,
                        )
                        .order_by(AgentVersionRow.version.desc())
                    )
                if prev is not None:
                    await self.rollback(tenant_id=tenant_id, agent_id=agent_id, to_version=prev.version)
                    rolled_back = prev.version
            return {
                "action": "stop",
                "reasons": reasons,
                "metrics": metrics,
                "halted": True,
                "rolled_back_to": rolled_back,
            }
        return {"action": "continue", "reasons": reasons, "metrics": metrics, "halted": False}

    async def resolve(self, *, tenant_id: str, agent_id: str, user_id: str | None = None) -> dict:
        """解析当前生效版本：灰度命中（user 哈希 < 百分比）返回灰度版，否则 ACTIVE。"""
        async with self.sessions() as s:
            grays = (
                await s.scalars(
                    select(AgentVersionRow)
                    .where(
                        AgentVersionRow.tenant_id == tenant_id,
                        AgentVersionRow.agent_id == agent_id,
                        AgentVersionRow.status == "GRAY",
                    )
                    .order_by(AgentVersionRow.version.desc())
                )
            ).all()
            active = await s.scalar(
                select(AgentVersionRow)
                .where(
                    AgentVersionRow.tenant_id == tenant_id,
                    AgentVersionRow.agent_id == agent_id,
                    AgentVersionRow.status == "ACTIVE",
                )
                .order_by(AgentVersionRow.version.desc())
            )
        if user_id:
            bucket = _stable_hash(user_id) % 100
            for gv in grays:
                cfg = json.loads(gv.config_json or "{}")
                if int(cfg.get("gray_percentage", 0)) > bucket:
                    return {
                        "version": gv.version,
                        "system_prompt": gv.system_prompt,
                        "model": gv.model,
                        "status": "GRAY",
                    }
        if active is None:
            raise AgentError(f"no ACTIVE version for agent {agent_id}", code="AGENT_VERSION_NOT_FOUND")
        return {
            "version": active.version,
            "system_prompt": active.system_prompt,
            "model": active.model,
            "status": "ACTIVE",
        }
