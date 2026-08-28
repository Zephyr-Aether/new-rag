"""CostService（§50.1/§50.2）：成本归因聚合 + 账单对账 + Token/Run 持续增长告警。

- overview：按 tenant/user/agent/version 聚合 runs 的 tokens/cost（下钻归因）。
- reconcile：估算 cost 按权威价重算，补 actual_cost 并校正 run.cost（账单口径）。
- growth：最近窗口 vs 前一窗口的 token-per-run 环比，涨幅超阈值告警（§50.2 持续上涨排查）。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.storage.models import AgentRunRow, LLMCallRow


def _now() -> datetime:
    return datetime.now(UTC)


class CostService:
    def __init__(self, sessions, *, settings=None):
        self.sessions = sessions
        self.settings = settings

    async def overview(
        self, *, tenant_id: str | None = None, user_id: str | None = None, since_days: int = 7
    ) -> list[dict]:
        where, params = [], {}
        if tenant_id:
            where.append("tenant_id = :tenant")
            params["tenant"] = tenant_id
        if user_id:
            where.append("user_id = :user")
            params["user"] = user_id
        if since_days:
            where.append("started_at >= :since")
            params["since"] = _now() - timedelta(days=since_days)
        sql = (
            "SELECT tenant_id, user_id, agent_id, agent_version, COUNT(*) AS runs, "
            "SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out, SUM(cost) AS cost "
            "FROM agent_runs"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " GROUP BY tenant_id, user_id, agent_id, agent_version ORDER BY cost DESC"
        )
        async with self.sessions() as s:
            rows = await s.execute(text(sql), params)
            return [dict(r._mapping) for r in rows]

    async def usage(self, *, tenant_id: str | None = None, days: int = 30) -> list[dict]:
        """按租户×日聚合用量（对客户计费/用量报表，§50.2）。"""
        where, params = ["started_at >= :since"], {"since": _now() - timedelta(days=days)}
        if tenant_id:
            where.append("tenant_id = :tenant")
            params["tenant"] = tenant_id
        sql = (
            "SELECT tenant_id, date(started_at) AS day, COUNT(*) AS runs, "
            "SUM(tokens_in + tokens_out) AS tokens, SUM(cost) AS cost "
            "FROM agent_runs WHERE "
            + " AND ".join(where)
            + " GROUP BY tenant_id, date(started_at) ORDER BY day DESC"
        )
        async with self.sessions() as s:
            rows = await s.execute(text(sql), params)
            return [dict(r._mapping) for r in rows]

    async def reconcile(
        self,
        *,
        tenant_id: str | None = None,
        run_id: str | None = None,
        prices: dict[str, tuple[float, float]] | None = None,
        bill: list[dict] | None = None,
        bill_provider=None,
    ) -> dict:
        """§50.1 账单对账上游：未对账 llm_calls 用真实账单校正 actual_cost，并校正 run.cost。

        bill 行 `[{run_id, step_id, cost}]`（provider 账单按请求标识 run+step）：
        命中用账单价；未命中回落价格计算（prices 或 settings 单价）。
        bill_provider 为账单拉取适配器（§50.1 接真实 provider），有则先 fetch_bill。
        """
        if bill_provider is not None and bill is None:
            bill = await bill_provider.fetch_bill(tenant_id=tenant_id)
        default_in = self.settings.llm_price_input_per_mtok if self.settings else 1.0
        default_out = self.settings.llm_price_output_per_mtok if self.settings else 3.0
        bill_cost = {f"{b['run_id']}:{b.get('step_id', '')}": float(b.get("cost", 0.0)) for b in bill or []}
        async with self.sessions() as s:
            q = select(LLMCallRow).where(LLMCallRow.actual_cost.is_(None))
            if tenant_id:
                q = q.where(LLMCallRow.tenant_id == tenant_id)
            if run_id:
                q = q.where(LLMCallRow.run_id == run_id)
            rows = (await s.scalars(q)).all()
            total_estimated = 0.0
            total_actual = 0.0
            matched_bill = 0
            fallback_priced = 0
            per_run: dict[str, float] = {}
            for r in rows:
                actual = bill_cost.get(f"{r.run_id}:{r.step_id}")
                if actual is not None:
                    matched_bill += 1
                else:
                    in_price, out_price = (
                        prices.get(r.model, (default_in, default_out))
                        if prices
                        else (default_in, default_out)
                    )
                    actual = (r.tokens_in or 0) / 1_000_000 * in_price + (
                        r.tokens_out or 0
                    ) / 1_000_000 * out_price
                    fallback_priced += 1
                r.actual_cost = actual
                total_estimated += r.estimated_cost or 0.0
                total_actual += actual
                per_run[r.run_id] = per_run.get(r.run_id, 0.0) + actual
            for run_id_u, cost in per_run.items():
                run = await s.get(AgentRunRow, run_id_u)
                if run is not None:
                    run.cost = round(cost, 6)
            await s.commit()
        return {
            "reconciled": len(rows),
            "matched_bill": matched_bill,
            "fallback_priced": fallback_priced,
            "runs_updated": len(per_run),
            "total_estimated": round(total_estimated, 6),
            "total_actual": round(total_actual, 6),
            "diff": round(total_actual - total_estimated, 6),
        }

    async def growth(self, *, window_days: int = 7, threshold: float = 1.05) -> list[dict]:
        """§50.2 Token/Run 环比：最近窗口 vs 前一窗口，涨幅超阈值即告警。"""
        now = _now()
        cur_start = now - timedelta(days=window_days)
        prev_start = now - timedelta(days=2 * window_days)
        sql = text(
            """
            SELECT tenant_id,
              SUM(CASE WHEN started_at >= :cur THEN tokens_in + tokens_out ELSE 0 END) AS cur_tokens,
              SUM(CASE WHEN started_at >= :cur THEN 1 ELSE 0 END) AS cur_runs,
              SUM(CASE WHEN started_at < :cur AND started_at >= :prev
                    THEN tokens_in + tokens_out ELSE 0 END) AS prev_tokens,
              SUM(CASE WHEN started_at < :cur AND started_at >= :prev
                    THEN 1 ELSE 0 END) AS prev_runs
            FROM agent_runs WHERE started_at >= :prev GROUP BY tenant_id
            """
        )
        async with self.sessions() as s:
            rows = await s.execute(sql, {"cur": cur_start, "prev": prev_start})
            out = []
            for r in rows:
                cur_tpr = (r.cur_tokens or 0) / r.cur_runs if r.cur_runs else 0.0
                prev_tpr = (r.prev_tokens or 0) / r.prev_runs if r.prev_runs else 0.0
                ratio = (cur_tpr / prev_tpr) if prev_tpr else None
                out.append(
                    {
                        "tenant_id": r.tenant_id,
                        "current_tokens_per_run": round(cur_tpr, 1),
                        "previous_tokens_per_run": round(prev_tpr, 1),
                        "ratio": round(ratio, 3) if ratio is not None else None,
                        "alert": bool(ratio and ratio > threshold),
                    }
                )
            return out
