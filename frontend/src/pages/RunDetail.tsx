import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  api,
  CompareResult,
  LLMCall,
  ReplayOverrides,
  RunCost,
  RunDetail as RunDetailT,
  ScheduleCompare,
  ScheduleDecision,
  Step,
  TracePayload,
} from '../api'
import { Badge, Button, Card, Empty, ErrorBox, Field, fmtCost, Loading, Modal, shortId, SuccessBox, TableSkeleton } from '../components/ui'
import { useConfirm } from '../components/Confirm'

const TERMINAL = ['COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'UNKNOWN']

type Citation = { document_id: string; section?: string; text?: string; score?: number }

function fmtTime(iso?: string): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    return ''
  }
}

function fmtDuration(ms: number): string {
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}秒`
  return `${Math.floor(s / 60)}分 ${s % 60}秒`
}

function TraceItem({
  step,
  call,
  bad,
}: {
  step: Step
  call?: LLMCall
  bad: boolean
}) {
  const [open, setOpen] = useState(false)
  const tools = step.tool_calls ?? []
  return (
    <div className={`trace-item ${bad ? 'bad' : 'ok'}`}>
      <div className="trace-head">
        <span className="trace-time">{fmtTime(step.created_at)}</span>
        <span className="mono small">Step #{step.seq}</span>
        <Badge status={step.state} />
        {step.llm && (
          <span className="small muted mono">
            {step.llm.model} · {call ? `${call.latency_ms}ms` : '—'} · {step.llm.tokens_in ?? 0}+{step.llm.tokens_out ?? 0} tok
            {call ? ` · $${fmtCost(call.estimated_cost)}` : ''}
          </span>
        )}
        {tools.length > 0 && (
          <button className="trace-toggle" onClick={() => setOpen(!open)}>
            {open ? '收起' : `查看 ${tools.length} 个工具调用`}
          </button>
        )}
      </div>
      {tools.length > 0 && (
        <div className="trace-tools">
          {tools.map((t) => (
            <span key={t.tool_ref} className={`trace-tool ${t.ok === false ? 'bad' : ''}`}>
              {t.tool_ref} {t.latency_ms ?? '?'}ms {t.ok === false ? '❌' : '✅'}
            </span>
          ))}
        </div>
      )}
      {open && (
        <div className="trace-detail">
          {step.llm?.tool_calls && step.llm.tool_calls.length > 0 && (
            <div className="trace-detail-block">
              <div className="muted small mb">LLM 工具意图（原始 arguments）</div>
              {step.llm.tool_calls.map((tc, i) => (
                <pre key={i} className="pretty">
                  {tc.name}({tc.arguments})
                </pre>
              ))}
            </div>
          )}
          {tools.map((t, i) => (
            <div key={i} className="trace-detail-block">
              <div className="muted small mb">
                {t.tool_ref} 结果 {t.ok === false ? '（失败）' : ''}
              </div>
              <pre className="pretty">{JSON.stringify(t.data ?? t, null, 2).slice(0, 1200)}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function OverridesFields({
  value,
  onChange,
}: {
  value: { model: string; system_prompt: string; top_k: string }
  onChange: (v: { model: string; system_prompt: string; top_k: string }) => void
}) {
  return (
    <>
      <Field label="模型覆盖（留空=沿用原 run）">
        <input value={value.model} onChange={(e) => onChange({ ...value, model: e.target.value })} placeholder="如 gpt-4o-mini" />
      </Field>
      <Field label="system_prompt 覆盖（留空=沿用）">
        <textarea
          value={value.system_prompt}
          onChange={(e) => onChange({ ...value, system_prompt: e.target.value })}
          placeholder="新的系统提示词"
        />
      </Field>
      <Field label="检索 top_k 覆盖（留空=沿用）">
        <input
          type="number"
          min={1}
          max={20}
          value={value.top_k}
          onChange={(e) => onChange({ ...value, top_k: e.target.value })}
        />
      </Field>
    </>
  )
}

function buildOverrides(v: { model: string; system_prompt: string; top_k: string }): ReplayOverrides {
  const o: ReplayOverrides = {}
  if (v.model.trim()) o.model = v.model.trim()
  if (v.system_prompt.trim()) o.system_prompt = v.system_prompt
  if (v.top_k.trim()) o.top_k = Number(v.top_k)
  return o
}

function ReplayModal({ runId, onClose }: { runId: string; onClose: () => void }) {
  const navigate = useNavigate()
  const [v, setV] = useState({ model: '', system_prompt: '', top_k: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  async function submit() {
    setBusy(true)
    setErr('')
    try {
      const r = await api.replayRun(runId, buildOverrides(v))
      onClose()
      navigate(`/runs/${r.run_id}`)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal title="重放：按原始输入与版本重新执行" onClose={onClose}>
      <OverridesFields value={v} onChange={setV} />
      {err && <ErrorBox message={err} />}
      <div className="row mt">
        <Button tone="primary" disabled={busy} onClick={submit}>
          {busy ? '重放中…' : '开始重放'}
        </Button>
        <Button onClick={onClose}>取消</Button>
      </div>
    </Modal>
  )
}

function CompareModal({ runId, onClose }: { runId: string; onClose: () => void }) {
  const [v, setV] = useState({ model: '', system_prompt: '', top_k: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [result, setResult] = useState<CompareResult | null>(null)
  async function submit() {
    setBusy(true)
    setErr('')
    try {
      setResult(await api.compareRun(runId, buildOverrides(v)))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal title="对比：重放并比较答案差异" onClose={onClose}>
      {!result ? (
        <>
          <OverridesFields value={v} onChange={setV} />
          {err && <ErrorBox message={err} />}
          <div className="row mt">
            <Button tone="primary" disabled={busy} onClick={submit}>
              {busy ? '重放对比中…' : '运行对比'}
            </Button>
            <Button onClick={onClose}>取消</Button>
          </div>
        </>
      ) : (
        <div className="grid" style={{ gap: 10 }}>
          <div className="row spread small">
            <span className="mono">原 {shortId(result.original_run)}</span>
            <span className="mono">重放 {shortId(result.replay_run)}</span>
          </div>
          <Badge status={result.diff.same ? 'pass' : 'warn'}>{result.diff.same ? '答案一致' : '答案有差异'}</Badge>
          {!result.diff.same && (
            <div className="grid cols-2" style={{ gap: 10 }}>
              <div>
                <div className="label small muted">原答案</div>
                <pre className="pretty">{result.original_answer ?? '—'}</pre>
              </div>
              <div>
                <div className="label small muted">重放答案</div>
                <pre className="pretty">{result.replay_answer ?? '—'}</pre>
              </div>
            </div>
          )}
          {!result.diff.same && (result.diff.removed || result.diff.added) && (
            <p className="small">
              {result.diff.removed && <span className="muted">- {result.diff.removed} </span>}
              {result.diff.added && <span className="ok">+ {result.diff.added}</span>}
            </p>
          )}
          <p className="small muted">
            检索 top_k：{result.retrieval.original_top_k ?? '默认'} → {result.retrieval.replay_top_k ?? '默认'}
            {result.retrieval.overridden ? '（已覆盖）' : ''}
          </p>
          <div className="row">
            <Button onClick={() => setResult(null)}>再次对比</Button>
            <Button onClick={onClose}>关闭</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function FeedbackBar({ runId }: { runId: string }) {
  const [stage, setStage] = useState<'idle' | 'bad' | 'done'>('idle')
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  async function send(feedback: 'good' | 'bad') {
    setErr('')
    try {
      const r = await api.runFeedback(runId, feedback, reason.trim())
      setNote(
        feedback === 'bad' && r.case_id
          ? `已记录，并自动进入 BADCASES 评测集（case ${shortId(r.case_id)}）`
          : '感谢反馈',
      )
      setStage('done')
    } catch (e) {
      setErr((e as Error).message)
    }
  }
  if (stage === 'done') return <SuccessBox message={note} />
  return (
    <div className="mt">
      <div className="row small">
        <span className="muted">这次回答有帮助吗？</span>
        <Button onClick={() => send('good')}>👍 有帮助</Button>
        <Button onClick={() => setStage('bad')}>👎 有问题</Button>
      </div>
      {stage === 'bad' && (
        <div className="row mt">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="问题描述（可选），将自动录入 badcase"
            style={{ flex: 1 }}
          />
          <Button tone="danger" onClick={() => send('bad')}>提交</Button>
        </div>
      )}
      {err && <ErrorBox message={err} />}
    </div>
  )
}

export default function RunDetail() {
  const { id = '' } = useParams()
  const [data, setData] = useState<RunDetailT | null>(null)
  const [cost, setCost] = useState<RunCost | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  const [showReplay, setShowReplay] = useState(false)
  const [showCompare, setShowCompare] = useState(false)
  const [decisions, setDecisions] = useState<ScheduleDecision[] | null>(null)
  const [schedCmp, setSchedCmp] = useState<ScheduleCompare | null>(null)
  const [payloads, setPayloads] = useState<TracePayload[] | null>(null)
  const [showPayloads, setShowPayloads] = useState(false)
  const { confirm, confirmEl } = useConfirm()

  const refresh = useCallback(async () => {
    const [d, c] = await Promise.all([api.runDetail(id), api.runCost(id)])
    setData(d)
    setCost(c)
  }, [id])

  useEffect(() => {
    refresh().catch((e: Error) => setErr(e.message))
  }, [refresh])

  // 进行中的 run 轮询：状态/步骤/成本自动刷新，终态即停
  const runState = data?.run.state ?? ''
  useEffect(() => {
    if (!data || TERMINAL.includes(runState)) return
    const t = setInterval(() => refresh().catch(() => undefined), 3000)
    return () => clearInterval(t)
  }, [data, runState, refresh])

  // 调度决策随详情加载
  useEffect(() => {
    if (!data) return
    api
      .runSchedule(id)
      .then((r) => setDecisions(r.decisions))
      .catch(() => setDecisions(null))
  }, [data, id])

  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key)
    setErr('')
    try {
      await fn()
      await refresh()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  function cancel() {
    confirm('取消任务', '确定取消这个任务吗？该操作不可恢复。', () => act('cancel', () => api.cancelRun(id)), { danger: true, confirmText: '取消任务' })
  }

  async function loadPayloads() {
    setShowPayloads(true)
    try {
      const r = await api.runPayloads(id)
      setPayloads(r.payloads)
    } catch {
      setPayloads([])
    }
  }

  async function compareSchedule() {
    setBusy('sched')
    setErr('')
    try {
      setSchedCmp(await api.scheduleCompare(id))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  if (err) return <ErrorBox message={err} />
  if (!data) return <Loading />

  const run = data.run
  const terminal = TERMINAL.includes(run.state)
  let answer: string | null = null
  try {
    answer = run.output_json ? (JSON.parse(run.output_json).answer ?? null) : null
  } catch {
    answer = null
  }
  let runError: { code?: string; message?: string } | null = null
  try {
    runError = run.error_json ? (JSON.parse(run.error_json) ?? null) : null
  } catch {
    runError = null
  }

  // 检索引用（provenance）：汇总全 run 中 kb.search 命中的文档，去重、限量
  const citations: Citation[] = []
  {
    const seen = new Set<string>()
    for (const s of data.steps) {
      for (const t of s.tool_calls ?? []) {
        if (t.tool_ref !== 'kb.search' || !Array.isArray(t.data)) continue
        for (const h of t.data) {
          const c = h as Citation | undefined
          if (!c?.document_id || seen.has(c.document_id)) continue
          seen.add(c.document_id)
          citations.push(c)
          if (citations.length >= 10) break
        }
        if (citations.length >= 10) break
      }
      if (citations.length >= 10) break
    }
  }

  const callByStep = new Map((cost?.llm_calls ?? []).map((c) => [c.step_id, c]))
  const conclusionText = runError
    ? '执行失败'
    : !terminal
      ? '执行中'
      : run.state === 'COMPLETED'
        ? '已完成'
        : '已终止'

  // 总耗时：按步骤时间戳首尾估算（步骤缺失时间戳则省略）
  const stepTimes = data.steps.map((s) => s.created_at).filter(Boolean) as string[]
  let duration: number | null = null
  if (stepTimes.length >= 2) {
    const nums = stepTimes.map((t) => new Date(t).getTime()).filter((n) => !Number.isNaN(n))
    if (nums.length >= 2) duration = Math.max(0, Math.max(...nums) - Math.min(...nums))
  }

  return (
    <div className="grid" style={{ gap: 18 }}>
      {confirmEl}
      {/* 页头：任务标识 + 状态 + 操作 */}
      <div className="page-header">
        <div>
          <div className="row">
            <h2 className="page-title mono">{shortId(run.run_id)}</h2>
            <Badge status={run.state} />
          </div>
          <p className="page-desc">
            任务执行报告 · agent v{run.agent_version} · {data.steps.length} 步 ·{' '}
            {conclusionText}
          </p>
        </div>
        <div className="page-actions">
          {run.state === 'PAUSED' ? (
            <Button tone="primary" disabled={busy === 'pause'} onClick={() => act('pause', () => api.resumeRun(run.run_id))}>
              恢复
            </Button>
          ) : (
            !terminal && (
              <>
                <Button disabled={busy === 'pause'} onClick={() => act('pause', () => api.pauseRun(run.run_id))}>
                  暂停
                </Button>
                <Button tone="danger" disabled={busy === 'cancel'} onClick={cancel}>
                  取消
                </Button>
              </>
            )
          )}
          <Button onClick={() => setShowReplay(true)}>重放</Button>
          <Button onClick={() => setShowCompare(true)}>对比</Button>
        </div>
      </div>

      {showReplay && <ReplayModal runId={run.run_id} onClose={() => setShowReplay(false)} />}
      {showCompare && <CompareModal runId={run.run_id} onClose={() => setShowCompare(false)} />}

      {/* 1. 结果摘要：结论先行 */}
      <Card title="结果摘要">
        <div className="row small muted" style={{ marginBottom: 10 }}>
          <span>
            agent v{run.agent_version} · {data.steps.length} 步{duration !== null ? ` · 耗时 ${fmtDuration(duration)}` : ''} · tokens {run.tokens_in}/{run.tokens_out} · 成本 ${fmtCost(run.cost)}
          </span>
        </div>
        {runError ? (
          <div className="fail-banner">
            <div className="t">{runError.code ?? '执行失败'}</div>
            <div>{runError.message}</div>
            <div className="row mt">
              <Button tone="primary" onClick={() => setShowReplay(true)}>
                重放调试
              </Button>
              <Button onClick={() => setShowCompare(true)}>对比原任务</Button>
            </div>
          </div>
        ) : answer ? (
          <div className="result-panel">{answer}</div>
        ) : (
          <Empty text="该任务尚未生成文本结果" />
        )}
        {terminal && <FeedbackBar runId={run.run_id} />}
      </Card>

      {/* 2. 执行时间线：关键步骤 + 工具调用与返回 */}
      <Card title={`执行时间线（${data.steps.length} 步）`}>
        {data.steps.length === 0 ? (
          <Empty text="无步骤" />
        ) : (
          <div className="trace-line">
            {data.steps.map((s) => {
              const failedTools = (s.tool_calls ?? []).some((t) => !t.ok)
              return <TraceItem key={s.seq} step={s} call={callByStep.get(String(s.seq))} bad={failedTools} />
            })}
          </div>
        )}
      </Card>

      {/* 3. 模型选择与路由 */}
      <Card title={`模型选择与路由（${decisions?.length ?? '…'}）`}>
        {decisions === null || decisions.length === 0 ? (
          <Empty text="无模型路由决策" />
        ) : (
          <>
            <table className="tbl">
              <thead>
                <tr>
                  <th>步骤</th>
                  <th>使用的模型</th>
                  <th>选择原因</th>
                </tr>
              </thead>
              <tbody>
                {decisions.map((d, i) => (
                  <tr key={i}>
                    <td className="mono small">{shortId(d.step_id)}</td>
                    <td className="mono">{d.model}</td>
                    <td className="small muted">{d.scheduler_reason || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="row mt">
              <Button disabled={busy === 'sched'} onClick={compareSchedule}>
                {busy === 'sched' ? '重放中…' : '重放并对比路由'}
              </Button>
            </div>
          </>
        )}
        {schedCmp && (
          <div className="grid cols-2 mt" style={{ gap: 10 }}>
            <div>
              <div className="small muted">原任务决策</div>
              <pre className="pretty small">
                {schedCmp.original_decisions.map((d) => `${d.model} · ${d.scheduler_reason ?? '-'}`).join('\n') || '—'}
              </pre>
            </div>
            <div>
              <div className="small muted">重放任务决策（{shortId(schedCmp.replay_run)}）</div>
              <pre className="pretty small">
                {schedCmp.replay_decisions.map((d) => `${d.model} · ${d.scheduler_reason ?? '-'}`).join('\n') || '—'}
              </pre>
            </div>
          </div>
        )}
      </Card>

      {/* 4. 检索来源与引用 */}
      {citations.length > 0 && (
        <Card title={`检索来源与引用（${citations.length} 篇文档）`}>
          <p className="small muted mb">上面的回答依据了这些文档。点进去可到知识库查看原文。</p>
          <div className="trace-tools">
            {citations.map((c, i) => (
              <Link
                key={`${c.document_id}-${i}`}
                className="trace-tool"
                to="/knowledge"
                title={`${c.section ?? ''}${c.text ? `\n${c.text}` : ''}`}
              >
                {c.document_id}
                {c.section ? ` · ${c.section}` : ''}
              </Link>
            ))}
          </div>
        </Card>
      )}

      {/* 5. 成本与 Token */}
      <Card title="成本与 Token">
        <div className="run-summary">
          <div className="metric">
            <div className="k">总成本</div>
            <div className="v">${fmtCost(cost?.totals.estimated_cost)}</div>
            <div className="small muted">tokens {cost?.totals.tokens_in}/{cost?.totals.tokens_out}</div>
          </div>
          <div className="metric">
            <div className="k">工具调用</div>
            <div className="v">{data.steps.reduce((a, s) => a + (s.tool_calls?.length ?? 0), 0)}</div>
            <div className="small muted">分布于 {data.steps.length} 步</div>
          </div>
          <div className="metric">
            <div className="k">LLM 平均延迟</div>
            <div className="v">
              {cost && cost.llm_calls.length
                ? `${Math.round(cost.llm_calls.reduce((a, c: LLMCall) => a + c.latency_ms, 0) / cost.llm_calls.length)}ms`
                : '—'}
            </div>
            <div className="small muted">每次调用</div>
          </div>
          <div className="metric">
            <div className="k">执行步数</div>
            <div className="v">{data.steps.length}</div>
            <div className="small muted">{cost?.llm_calls.length ?? 0} 次 LLM 调用</div>
          </div>
        </div>
        {cost && cost.llm_calls.length > 0 && (
          <div className="mt">
            <div className="label small muted mb">每次模型调用明细</div>
            <table className="tbl">
              <thead>
                <tr>
                  <th>模型</th>
                  <th>步骤</th>
                  <th className="num">tokens</th>
                  <th className="num">输入分项 P/H/T/R</th>
                  <th className="num">延迟</th>
                  <th className="num">成本</th>
                </tr>
              </thead>
              <tbody>
                {cost.llm_calls.map((c, i) => (
                  <tr key={i}>
                    <td className="mono">{c.model}</td>
                    <td className="mono small">{shortId(c.step_id)}</td>
                    <td className="num">{c.tokens_in}/{c.tokens_out}</td>
                    <td className="num mono small">
                      {(c.prompt_tokens ?? 0)}/{c.history_tokens ?? 0}/{c.tool_tokens ?? 0}/{c.rag_tokens ?? 0}
                    </td>
                    <td className="num">{c.latency_ms}ms</td>
                    <td className="num mono">{fmtCost(c.estimated_cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* 6. 错误 · 重试 · 回放：不满意时怎么处理 */}
      <Card title="错误 · 重试 · 回放">
        <p className="small muted mb">
          对结果不满意时，可以重跑一次（重放）或对比不同配置下的答案；系统也会按采样率保留调试轨迹。
        </p>
        <div className="row">
          <Button onClick={() => setShowReplay(true)}>重放调试</Button>
          <Button onClick={() => setShowCompare(true)}>对比答案</Button>
        </div>
        <div className="mt">
          <div className="label small muted mb">调试采样（Trace Payload）</div>
          {!showPayloads ? (
            <Button onClick={loadPayloads}>加载采样轨迹</Button>
          ) : payloads === null ? (
            <TableSkeleton rows={5} cols={5} />
          ) : payloads.length === 0 ? (
            <Empty text="该任务未被采样（采样率由 trace_payload_rate 控制）" />
          ) : (
            payloads.map((p) => (
              <details key={p.id} className="mt">
                <summary className="small mono">
                  #{p.id} {p.span_name} <span className="muted">{p.kind}</span>
                </summary>
                <pre className="pretty small">{JSON.stringify(p.payload, null, 2)}</pre>
              </details>
            ))
          )}
        </div>
      </Card>
    </div>
  )
}