import { useState } from 'react'
import { Pagination } from '@/components/pagination'
import { useRequest } from 'ahooks'
import { useNavigate } from 'react-router-dom'
import { api } from '@/services'
import { Badge, Bar, Button, Card, ErrorBox, fmtCost, shortId, SuccessBox, TableSkeleton } from '@/components'
import { EmptyState, PageError, PageHeader } from '@/components/Page'

const PAGE_SIZE = 10

export default function Cost() {
  const navigate = useNavigate()
  const { data, loading, error, refresh } = useRequest(() =>
    Promise.all([api.costOverview(), api.costGrowth()]),
  )
  const rows = data?.[0].rows ?? null
  const growth = data?.[1].rows ?? null
  const [reconcileMsg, setReconcileMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [page, setPage] = useState(1)

  async function reconcile() {
    setBusy(true)
    setReconcileMsg(null)
    try {
      const r = await api.reconcile()
      setReconcileMsg({
        kind: 'ok',
        text: `对账 ${r.reconciled} 条调用（${r.runs_updated} run），估算 $${r.total_estimated} → 实际 $${r.total_actual}（差 $${r.diff}）`,
      })
    } catch (e) {
      setReconcileMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  const totalCost = (rows ?? []).reduce((a, r) => a + r.cost, 0)
  const totalRuns = (rows ?? []).reduce((a, r) => a + r.runs, 0)
  const top = rows && rows.length ? [...rows].sort((a, b) => b.cost - a.cost)[0] : null
  const g = growth ? growth[0] : undefined
  const ratio = g?.ratio ?? null
  const rising = g?.alert || (ratio !== null && ratio > 1.1)

  let advice = '成本数据还太少，多跑几次任务后这里会给出控制建议。'
  if (rows && rows.length > 0) {
    if (rising) advice = 'Token/任务环比上升：建议先收紧知识检索的候选数，或走模型降级路径压一压成本。'
    else if (top) advice = `主要成本集中在 ${shortId(top.agent_id)} v${top.agent_version}，要省钱从这里入手：优化检索命中量或改用更小的模型。`
    else advice = '成本整体平稳，可以放心放量；发布前仍建议先过一遍效果评测。'
  }

  return (
    <div>
      <PageHeader
        title="成本"
        desc="成本归因 / Token 环比 / 账单对账"
        actions={
          <Button tone="primary" disabled={busy} onClick={reconcile}>
            {busy ? '对账中…' : '账单对账'}
          </Button>
        }
      />
      <div className="grid" style={{ gap: 16 }}>
      {error && <PageError message={(error as Error).message} retry={() => refresh()} />}
      {reconcileMsg && (reconcileMsg.kind === 'ok' ? <SuccessBox message={reconcileMsg.text} /> : <ErrorBox message={reconcileMsg.text} />)}

        <Card title="结论与建议">
          {rows === null ? (
            <TableSkeleton rows={2} cols={3} />
          ) : rows.length === 0 ? (
            <EmptyState
            title="还没有成本数据"
            desc="跑几次任务后，这里会统计累计成本、主要来源与环比趋势，并给出控制建议。"
            actionLabel="去发起任务"
            action={() => navigate('/runs')}
          />
          ) : (
            <>
              <div className="row" style={{ marginBottom: 10 }}>
                <span>累计估算成本 <b>${fmtCost(totalCost)}</b></span>
                <span className="muted small">· {totalRuns} 次任务</span>
                {top && (
                  <span className="muted small">
                    · 主要来源 <span className="mono">{shortId(top.agent_id)}</span> v{top.agent_version}
                  </span>
                )}
              </div>
              <div className="row" style={{ marginBottom: 12 }}>
                <span className="small">Token/任务：{g ? g.current_tokens_per_run.toLocaleString() : '—'} tok/run</span>
                {ratio !== null && g && (
                  <Badge status={g.alert ? 'fail' : 'pass'}>
                    {(ratio - 1) * 100 >= 0 ? '+' : ''}
                    {(((ratio ?? 1) - 1) * 100).toFixed(1)}%
                    {g.alert ? '（需关注）' : ''}
                  </Badge>
                )}
              </div>
              <div className="home-hint" style={{ marginBottom: 0 }}>
                <span>💡 {advice}</span>
              </div>
            </>
          )}
        </Card>

        <Card title="成本归因（按 Agent / 版本）" className="">
          {loading ? (
            <TableSkeleton rows={5} cols={5} />
          ) : (rows ?? []).length === 0 ? (
            <EmptyState
            title="还没有可归因的成本"
            desc="这里按 Agent / 版本拆分每次任务的花费；跑几次任务后即可查看。"
            actionLabel="去发起任务"
            action={() => navigate('/runs')}
          />
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>v</th>
                  <th className="num">runs</th>
                  <th className="num">tokens</th>
                  <th className="num">成本</th>
                  <th>占比</th>
                </tr>
              </thead>
              <tbody>
                {(rows ?? []).slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((r, i) => {
                  const max = Math.max(...(rows ?? []).map((x) => x.cost), 0.0001)
                  return (
                    <tr key={i}>
                      <td className="mono">{shortId(r.agent_id)}</td>
                      <td className="mono">{r.agent_version}</td>
                      <td className="num">{r.runs}</td>
                      <td className="num">{r.tokens_in}/{r.tokens_out}</td>
                      <td className="num mono">${fmtCost(r.cost)}</td>
                      <td>
                        <div className="row" style={{ gap: 8 }}>
                          <Bar value={r.cost / max} />
                          <span className="mono small">{Math.round((r.cost / max) * 100)}%</span>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
          {(rows?.length ?? 0) > PAGE_SIZE && (
            <div className="row mt" style={{ justifyContent: 'flex-end' }}>
              <Pagination current={page} pageSize={PAGE_SIZE} total={rows?.length ?? 0} onChange={setPage} />
            </div>
          )}
        </Card>

      <Card title="Token/任务 环比（当前 vs 前一窗口）">
        {growth === null ? (
          <TableSkeleton rows={5} cols={5} />
        ) : growth.length === 0 ? (
          <EmptyState
            title="还没有环比数据"
            desc="需要两个统计窗口的任务数据，才能对比 Token / 任务的变化。"
          />
        ) : (
          <div className="grid cols-2" style={{ gap: 14 }}>
            {growth.map((g, i) => {
              const max = Math.max(g.current_tokens_per_run, g.previous_tokens_per_run, 1)
              const curPct = Math.round((g.current_tokens_per_run / max) * 100)
              const prevPct = Math.round((g.previous_tokens_per_run / max) * 100)
              return (
                <div key={i} className="stat" style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
                  <div className="label mono">{g.tenant_id}</div>
                  <div style={{ marginTop: 10 }}>
                    <div className="small muted" style={{ marginBottom: 4 }}>
                      当前 {g.current_tokens_per_run.toLocaleString()} tok/run
                    </div>
                    <div className="bar" style={{ height: 14 }}>
                      <div style={{ width: `${curPct}%`, height: '100%', background: g.alert ? 'var(--red)' : 'var(--accent-2)' }} />
                    </div>
                    <div className="small muted" style={{ marginTop: 8, marginBottom: 4 }}>
                      前窗口 {g.previous_tokens_per_run.toLocaleString()} tok/run
                    </div>
                    <div className="bar" style={{ height: 14 }}>
                      <div style={{ width: `${prevPct}%`, height: '100%', background: 'var(--text-2)' }} />
                    </div>
                    <div style={{ marginTop: 8 }}>
                      {g.ratio === null ? (
                        <span className="muted small">— 无前一窗口</span>
                      ) : (
                        <Badge status={g.alert ? 'fail' : 'pass'}>
                          {(g.ratio ?? 1) - 1 >= 0 ? '+' : ''}
                          {(((g.ratio ?? 1) - 1) * 100).toFixed(1)}%
                        </Badge>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Card>
      </div>
    </div>
  )
}
