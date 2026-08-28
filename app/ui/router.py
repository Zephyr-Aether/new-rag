"""UI 路由（§18 开发调试 Console / §19 审批控制台）。

GET /ui/approvals           审批控制台（待审批 + 批准/拒绝）
GET /ui/runs                运行列表
GET /ui/runs/{run_id}       Run Timeline（§18：步骤/LLM/工具 时间线）
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.common.errors import AgentError
from app.state import AppState

router = APIRouter(prefix="/ui", tags=["ui"])


def _render_approvals(pending: list[dict]) -> str:
    rows = "".join(
        f"""
        <tr>
          <td>{a["approval_id"][:8]}</td>
          <td>{a["tool_ref"]}</td>
          <td>{a["risk_level"]}</td>
          <td>{a["requester_id"]}</td>
          <td>
            <form method="post" action="/approvals/{a["approval_id"]}/approve" style="display:inline">
              <input type="hidden" name="approver_id" value="console-admin"/>
              <button>批准</button>
            </form>
            <form method="post" action="/approvals/{a["approval_id"]}/reject" style="display:inline">
              <input type="hidden" name="approver_id" value="console-admin"/>
              <button>拒绝</button>
            </form>
          </td>
        </tr>"""
        for a in pending
    )
    return f"""<!doctype html><html lang="zh">
<head><meta charset="utf-8"><title>审批控制台</title></head><body>
<h1>审批控制台</h1><p>待审批：{len(pending)} 条</p>
<table border="1" cellspacing="0" cellpadding="6">
<tr><th>ID</th><th>工具</th><th>风险级</th><th>申请人</th><th>操作</th></tr>{rows}</table>
</body></html>"""


def _render_runs(runs: list[dict]) -> str:
    rows = "".join(
        f'<tr><td><a href="/ui/runs/{r["run_id"]}">{r["run_id"][:8]}</a></td>'
        f"<td>{r['state']}</td><td>tokens {r['tokens_in']}/{r['tokens_out']}</td>"
        f"<td>cost {r['cost']}</td></tr>"
        for r in runs
    )
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>Run 列表</title></head><body>
<h1>Run 列表</h1><table border="1" cellspacing="0" cellpadding="6">
<tr><th>Run</th><th>状态</th><th>Tokens</th><th>Cost</th></tr>{rows}</table></body></html>"""


def _render_timeline(run: dict, steps: list[dict], calls: list[dict]) -> str:
    call_latency = {c["model"]: c["latency_ms"] for c in calls}
    rows = ""
    for s in steps:
        llm = s.get("llm") or {}
        created = (s.get("created_at") or "").isoformat() if s.get("created_at") else ""
        llm_desc = (
            f"llm({llm.get('model', '?')} · {call_latency.get(llm.get('model'), '?')}ms · "
            f"{llm.get('tokens_in', 0)}+{llm.get('tokens_out', 0)} tokens)"
            if llm
            else "llm(?)"
        )
        tools = "".join(
            f'<span style="margin-right:8px">🔧 {o["tool_ref"]} {o.get("latency_ms", "?")}ms'
            f"{' ✅' if o.get('ok') else ' ❌'}</span>"
            for o in s.get("tool_calls", [])
        )
        rows += (
            f"<tr><td>Step #{s['seq']}</td><td>{s.get('state', '')}</td>"
            f"<td>{created}</td><td>{llm_desc}</td><td>{tools}</td></tr>"
        )
    run_id = run["run_id"]
    return f"""<!doctype html><html lang="zh">
<head><meta charset="utf-8"><title>Run Timeline</title></head><body>
<h1>Run Timeline</h1>
<p>run_id: {run_id} | state: <b>{run["state"]}</b> | cost: {run["cost"]} |
tokens: {run["tokens_in"]}/{run["tokens_out"]} | agent_version: {run["agent_version"]}</p>
<p><a href="/agents/runs/{run_id}/replay">⏵ Replay</a> ·
<a href="/agents/runs/{run_id}/compare">⏵ Compare</a> ·
<a href="/agents/runs/{run_id}/schedule">⏵ 调度决策</a> ·
<a href="/agents/runs/{run_id}/cost">⏵ 成本</a></p>
<table border="1" cellspacing="0" cellpadding="6">
<tr><th>Step</th><th>状态</th><th>时间</th><th>LLM</th><th>工具</th></tr>{rows}</table>
<p><a href="/ui/runs">← Run 列表</a></p></body></html>"""


@router.get("/approvals", response_class=HTMLResponse)
async def approval_console(request: Request) -> str:
    state: AppState = request.app.state.agent
    pending = await state.approvals.list_pending()
    return _render_approvals(pending)


@router.get("/runs", response_class=HTMLResponse)
async def runs_list(request: Request) -> str:
    state: AppState = request.app.state.agent
    runs = await state.store.list_runs(limit=100)
    return _render_runs(runs)


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_timeline(run_id: str, request: Request) -> str:
    """§18 Run Timeline：步骤/LLM/工具 时间线（调试 Console）。"""
    state: AppState = request.app.state.agent
    run = await state.store.get_run(run_id)
    if run is None:
        raise AgentError(f"run not found: {run_id}", code="RUN_NOT_FOUND")
    steps = await state.store.list_steps(run_id)
    calls = await state.store.list_llm_calls(run_id)
    return _render_timeline(run, steps, calls)
