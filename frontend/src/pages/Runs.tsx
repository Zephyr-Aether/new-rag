import { FormEvent, useRef, useState } from 'react'
import { useRequest } from 'ahooks'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Badge, Button, Card, Empty, ErrorBox, Field, fmtCost, fmtTime, shortId, stateLabel, SuccessBox, TableSkeleton } from '../components/ui'
import { PageHeader } from '../components/Page'

const PAGE = 20

export default function Runs() {
  const [input, setInput] = useState('')
  const [awaiting, setAwaiting] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [stateFilter, setStateFilter] = useState('')
  const [hasMore, setHasMore] = useState(false)
  const offsetRef = useRef(0)
  const { data, loading, run, mutate } = useRequest(
    () => api.listRuns(PAGE, offsetRef.current),
    { onSuccess: (r) => { offsetRef.current = r.runs.length; setHasMore(r.runs.length === PAGE) } },
  )
  const runs = data?.runs ?? null
  const filteredRuns = (runs ?? []).filter((r) => !stateFilter || r.state === stateFilter)
  const totalRuns = runs?.length ?? 0
  const failedRuns = (runs ?? []).filter((r) => r.state === 'FAILED').length
  const modeLabel = awaiting ? '同步等待结果' : '异步入队追踪'

  async function refresh(loadMore = false) {
    if (loadMore) {
      const r = await api.listRuns(PAGE, offsetRef.current)
      mutate((prev) => ({ runs: [...(prev?.runs ?? []), ...r.runs], total: r.total }))
      offsetRef.current += r.runs.length
      setHasMore(r.runs.length === PAGE)
    } else {
      offsetRef.current = 0
      run()
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!input.trim() || busy) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await api.createRun(input.trim(), awaiting)
      setInput('')
      if (awaiting) {
        setMsg({ kind: 'ok', text: `完成：${(r.answer || '').slice(0, 60)}` })
      } else {
        const runId = r.run_id
        setMsg({ kind: 'ok', text: `已入队（${shortId(runId)}），正在等待完成…` })
        refresh()
        // 轮询直到终态（最多 30s）
        const terminal = ['COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'UNKNOWN']
        void (async () => {
          for (let i = 0; i < 60; i++) {
            await new Promise((res) => setTimeout(res, 500))
            try {
              const detail = await api.runDetail(runId)
              if (terminal.includes(detail.run.state)) {
                setMsg({ kind: 'ok', text: `运行 ${shortId(runId)} → ${stateLabel(detail.run.state)}` })
                refresh()
                return
              }
            } catch {
              return
            }
          }
        })()
      }
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid" style={{ gap: 18 }}>
      <PageHeader
        title="任务运行"
        desc="输入一句话触发一次 Agent 执行；同步适合快验答案，异步适合看队列轨迹和失败原因。"
        actions={
          <>
            <Link className="btn" to="/knowledge">去知识库</Link>
            <Link className="btn primary" to="/chat">去对话</Link>
          </>
        }
      />

      <div className="home-hint">
        <div className="home-hint-copy">
          <span className="home-hint-kicker">推荐路径</span>
          <span>先试一个短问题确认模型能跑，再切到异步看队列和任务详情。知识问题可以直接写“知识库: ...”。</span>
          <span className="small muted" style={{ color: 'inherit' }}>{modeLabel}</span>
        </div>
        {awaiting ? (
          <Button onClick={() => setAwaiting(false)}>切到异步</Button>
        ) : (
          <Button onClick={() => setAwaiting(true)}>切到同步</Button>
        )}
      </div>

      <Card title="运行速览">
        <div className="run-summary">
          <div className="metric">
            <div className="k">执行模式</div>
            <div className="v">{awaiting ? '同步' : '异步'}</div>
            <div className="sub">{modeLabel}</div>
          </div>
          <div className="metric">
            <div className="k">当前筛选</div>
            <div className="v">{stateFilter ? stateLabel(stateFilter) : '全部'}</div>
            <div className="sub">只影响下面的列表</div>
          </div>
          <div className="metric">
            <div className="k">已加载</div>
            <div className="v">{totalRuns}</div>
            <div className="sub">条运行记录</div>
          </div>
          <div className="metric">
            <div className="k">失败数</div>
            <div className="v">{failedRuns}</div>
            <div className="sub">当前列表内</div>
          </div>
        </div>
      </Card>

      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="发起任务">
          <form onSubmit={submit}>
            <Field label="输入">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="例如：12 + 30  /  知识库: 退款到账时间"
              />
            </Field>
            <Field label="执行方式" className="row">
              <select value={awaiting ? 'sync' : 'async'} onChange={(e) => setAwaiting(e.target.value === 'sync')}>
                <option value="sync">同步（等待结果）</option>
                <option value="async">异步（入队）</option>
              </select>
            </Field>
            <Button tone="primary" disabled={busy || !input.trim()}>
              {busy ? '执行中…' : '执行任务'}
            </Button>
          </form>
          {msg && <div className="mt">{msg.kind === 'ok' ? <SuccessBox message={msg.text} /> : <ErrorBox message={msg.text} />}</div>}
        </Card>

        <Card title={`任务列表（${loading ? '…' : filteredRuns.length}）`}>
          <div className="row mb">
            {['', 'COMPLETED', 'FAILED', 'PAUSED', 'UNKNOWN', 'CANCELLED', 'TIMEOUT'].map((s) => (
              <button
                key={s}
                className={`btn ${stateFilter === s ? 'primary' : ''}`}
                onClick={() => setStateFilter(s)}
              >
                {s ? stateLabel(s) : '全部'}
              </button>
            ))}
          </div>
          {loading ? (
            <TableSkeleton rows={5} cols={5} />
          ) : (runs ?? []).length === 0 ? (
            <Empty text="还没有任务，先发起一次吧" />
          ) : filteredRuns.length === 0 ? (
            <Empty text="这个筛选下还没有任务" />
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>运行ID</th>
                  <th>问题</th>
                  <th>状态</th>
                  <th>版本</th>
                  <th>时间</th>
                  <th>错误</th>
                  <th className="num">成本</th>
                </tr>
              </thead>
              <tbody>
                {filteredRuns.map((r) => (
                    <tr key={r.run_id}>
                      <td className="mono">
                        <Link className="link" to={`/runs/${r.run_id}`}>
                          {shortId(r.run_id)}
                        </Link>
                      </td>
                      <td className="small">{r.input ? (r.input.length > 36 ? `${r.input.slice(0, 36)}…` : r.input) : '—'}</td>
                      <td>
                        <Badge status={r.state} />
                      </td>
                      <td>{r.agent_version}</td>
                      <td className="mono small">{fmtTime(r.started_at)}</td>
                      <td className="small muted">
                        {r.state === 'FAILED' ? (r.error?.code ?? '—') : '—'}
                      </td>
                      <td className="num mono">{fmtCost(r.cost)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
          {hasMore && (
            <div className="row mt">
              <Button
                disabled={busy}
                onClick={async () => {
                  setBusy(true)
                  try {
                    await refresh(true)
                  } catch (e) {
                    setMsg({ kind: 'err', text: (e as Error).message })
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                加载更多
              </Button>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
