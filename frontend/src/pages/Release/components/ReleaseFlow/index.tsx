import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, CanaryCheck, ContractCheck, Regression, Version } from '@/api'
import { Badge, Button, Card, Field, fmtTime } from '@/components/ui'
import { getLoginDraft } from '@/util/loginDraft'

type StepKey = 'draft' | 'contract' | 'regression' | 'gray' | 'release'

interface Exec {
  ts: string
  operator: string
  summary: string
  ok: boolean
  detail?: string
}

const STEPS: { key: StepKey; title: string; lockedHint: string }[] = [
  { key: 'draft', title: '创建草稿', lockedHint: '' },
  { key: 'contract', title: '契约检查', lockedHint: '需先创建草稿' },
  { key: 'regression', title: '回归评测', lockedHint: '需先通过契约检查' },
  { key: 'gray', title: '灰度放量', lockedHint: '需先通过回归评测' },
  { key: 'release', title: '全量上线 / 回滚', lockedHint: '需先进入灰度' },
]

const HIST_KEY = 'release_flow_history_v1'
const POLL_MS = 8000

function loadHistory(): Partial<Record<StepKey, Exec[]>> {
  try {
    return JSON.parse(localStorage.getItem(HIST_KEY) || '{}')
  } catch {
    return {}
  }
}
function saveHistory(h: Partial<Record<StepKey, Exec[]>>) {
  try {
    localStorage.setItem(HIST_KEY, JSON.stringify(h))
  } catch {
    /* ignore */
  }
}

interface ReleaseFlowProps {
  agentId: string
  versions: Version[] // 已按 version 倒序
  canPublish: boolean
  busy: string
  contractFor: { version: number; data: ContractCheck } | null
  regFor: { version: number; data: Regression } | null
  onChanged: () => void
  onOpenWizard: () => void
  onCreateVersion: (body: { system_prompt: string; model?: string; config?: Record<string, unknown> }) => void
  onRunContract: (v: number) => void
  onRunRegression: (v: number) => void
  onRunCanary: (v: number) => void
  onGray: (v: number) => void
  onPublish: (v: number) => void
  onRollback: (v: number) => void
  onHalt: (v: number) => void
}

export default function ReleaseFlow({
  agentId,
  versions,
  canPublish,
  busy,
  contractFor,
  regFor,
  onChanged,
  onOpenWizard,
  onCreateVersion,
  onRunContract,
  onRunRegression,
  onRunCanary,
  onGray,
  onPublish,
  onRollback,
  onHalt,
}: ReleaseFlowProps) {
  const pl = versions
  const latest = pl[0]
  const draft = latest?.status === 'DRAFT' ? latest : null
  const gray = pl.find((v) => v.status === 'GRAY') ?? null
  const active = pl.find((v) => v.status === 'ACTIVE') ?? null
  const hasGray = !!gray
  const hasActive = !!active

  // —— 展示步骤 + 通过标记 + 历史 ——
  const [viewStep, setViewStep] = useState(0)
  const [passedContract, setPassedContract] = useState(false)
  const [passedRegression, setPassedRegression] = useState(false)
  const [history, setHistory] = useState<Partial<Record<StepKey, Exec[]>>>(loadHistory)
  const latestDraftRef = useRef(latest?.version ?? -1)
  const prevLatestRef = useRef<string | undefined>(undefined)

  /** 当前该操作的步骤：无版本→草稿；有草稿→契约(过→回归→灰度)；灰/上线→放量决策。 */
  const autoStep = !latest ? 0 : latest.status === 'DRAFT' ? (passedRegression ? 3 : passedContract ? 2 : 1) : 4
  /** 流程是否已全部走通（上线且无待办）：完成态只读，但可回看全部步骤。 */
  const flowComplete = hasActive && !draft && !hasGray

  // 自动跟随推进：完成一步后，展示自动落到下一步
  useEffect(() => {
    setViewStep((prev) => Math.max(prev, autoStep))
  }, [autoStep])

  function record(key: StepKey, summary: string, ok: boolean, detail?: string) {
    const rec: Exec = { ts: new Date().toISOString(), operator: getLoginDraft().user || '—', summary, ok, detail }
    setHistory((prev) => {
      const next = { ...prev, [key]: [rec, ...(prev[key] ?? [])].slice(0, 3) }
      saveHistory(next)
      return next
    })
  }

  // 状态型动作（创建/灰度/发布）靠 refresh 带来的版本变化推进 + 留痕
  useEffect(() => {
    if (!latest) {
      setViewStep(0)
      prevLatestRef.current = undefined
      return
    }
    const prevStatus = prevLatestRef.current
    prevLatestRef.current = latest.status
    if (latest.status === 'DRAFT' && latest.version !== latestDraftRef.current) {
      latestDraftRef.current = latest.version
      record('draft', `创建草稿 v${latest.version}`, true)
      setViewStep(1)
      return
    }
    if (prevStatus && prevStatus !== latest.status) {
      if (latest.status === 'GRAY') record('gray', `灰度放量 v${latest.version}`, true)
      else if (latest.status === 'ACTIVE') record('release', `全量上线 v${latest.version}`, true)
      else if (latest.status === 'DISABLED') record('release', `停用 / 回滚 v${latest.version}`, true)
    }
    setViewStep((prev) => Math.max(prev, latest.status === 'DRAFT' ? 1 : 4))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versions])

  // 报告型动作：契约/回归结果 → 推进 + 留痕
  useEffect(() => {
    if (!contractFor) return
    const passed = contractFor.data.checks.filter((c) => c.status === 'pass').length
    const failed = contractFor.data.checks.filter((c) => c.status === 'fail').length
    setPassedContract(!contractFor.data.blocked)
    record('contract', `v${contractFor.version} 契约检查：${passed} 通过 / ${failed} 失败`, !contractFor.data.blocked, contractFor.data.checks.filter((c) => c.status !== 'pass').map((c) => `${c.id}: ${c.reason}`).join('；') || undefined)
    if (!contractFor.data.blocked) setViewStep((prev) => Math.max(prev, 2))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contractFor])
  useEffect(() => {
    if (!regFor) return
    const rate = (regFor.data.pass_rate ?? 0) * 100
    const delta = regFor.data.previous_pass_rate == null ? null : rate - regFor.data.previous_pass_rate * 100
    const word = regFor.data.regressed ? (delta !== null && delta < -10 ? '明显退化' : '轻微退化') : '未退化'
    setPassedRegression(!regFor.data.regressed)
    record('regression', `v${regFor.version} 回归：通过率 ${rate.toFixed(0)}% · ${word}`, !regFor.data.regressed)
    if (!regFor.data.regressed) setViewStep((prev) => Math.max(prev, 3))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [regFor])

  // 放量阶段 Canary：进入时拉一次，随后轮询实时刷新
  const [canary, setCanary] = useState<CanaryCheck | null>(null)
  const [canaryBusy, setCanaryBusy] = useState(false)
  useEffect(() => {
    if (!gray) {
      setCanary(null)
      return
    }
    let alive = true
    const fetchCanary = () =>
      api
        .canaryEvaluate(agentId)
        .then((c) => alive && setCanary(c))
        .catch(() => undefined)
        .finally(() => alive && setCanaryBusy(false))
    setCanaryBusy(true)
    fetchCanary()
    const timer = setInterval(fetchCanary, POLL_MS)
    return () => {
      alive = false
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, gray?.version])

  // 版本轮询：实时刷新发布状态（版本目录/流水线）
  useEffect(() => {
    const timer = setInterval(() => onChanged(), POLL_MS)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // —— 步骤状态 ——
  const doneMap: Record<StepKey, boolean> = {
    draft: pl.length > 0,
    contract: hasGray || hasActive || passedContract,
    regression: hasGray || hasActive || passedRegression,
    gray: hasGray,
    release: hasActive,
  }
  const failedMap: Record<StepKey, boolean> = {
    draft: false,
    contract: !!contractFor?.data.blocked,
    regression: !!regFor?.data.regressed,
    gray: false,
    release: false,
  }

  /** 门禁：上一步没做完，不能切到下一步；完成态可自由回看。 */
  function canSelect(i: number) {
    if (flowComplete) return true
    if (i === 0) return true
    return i <= autoStep || doneMap[STEPS[i - 1].key]
  }

  /** 该步骤是否可以操作（否则只读）：仅当前该做的一步可操作；完成态只允许在草稿步开新版本。 */
  function operable(i: number) {
    if (flowComplete) return i === 0
    return i === autoStep && !doneMap[STEPS[i].key]
  }

  const cur = STEPS[viewStep]
  const histForStep = history[cur.key] ?? []
  const readOnly = !operable(viewStep)

  // —— 创建草稿表单 ——
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState('')
  const [tools, setTools] = useState('calc.add')
  const [kv, setKv] = useState('0')
  const latestDraftConfig = pl.find((v) => v.status === 'DRAFT')?.config
  function importLastConfig() {
    const cfg = latestDraftConfig ?? pl.find((v) => v.status !== 'DRAFT')?.config
    if (!cfg) return
    setPrompt(String(cfg.system_prompt ?? ''))
    setModel(String(cfg.model ?? ''))
    setTools(Array.isArray(cfg.tools) ? (cfg.tools as string[]).join(', ') : 'calc.add')
    setKv(String(cfg.knowledge_version ?? '0'))
  }
  function loadTemplate() {
    setPrompt('你是企业客服助手，回答要基于知识库，不确定时明确说明，不编造。')
    setModel('')
    setTools('calc.add, kb.search')
    setKv('0')
  }
  function submitDraft() {
    if (!prompt.trim()) return
    onCreateVersion({
      system_prompt: prompt.trim(),
      model: model.trim() || undefined,
      config: { tools: tools.split(',').map((s) => s.trim()).filter(Boolean), knowledge_version: kv.trim() || '0' },
    })
  }

  const contractSummary = contractFor
    ? {
        total: contractFor.data.checks.length,
        passed: contractFor.data.checks.filter((c) => c.status === 'pass').length,
        blocked: contractFor.data.checks.filter((c) => c.status === 'fail').length,
        fails: contractFor.data.checks.filter((c) => c.status === 'fail'),
      }
    : null

  return (
    <div className="grid" style={{ gap: 18 }}>
      {/* 版本摘要条 */}
      <Card>
        <div className="release-summary">
          <div className="release-summary-item">
            <span className="release-summary-label">当前版本</span>
            <span className="release-summary-value">{latest ? `v${latest.version}` : '暂无'}</span>
          </div>
          <div className="release-summary-item">
            <span className="release-summary-label">状态</span>
            <span className="release-summary-value">{latest ? <Badge status={latest.status} /> : '—'}</span>
          </div>
          <div className="release-summary-item">
            <span className="release-summary-label">更新时间</span>
            <span className="release-summary-value">{latest?.created_at ? fmtTime(latest.created_at) : '—'}</span>
          </div>
          <div className="release-summary-item">
            <span className="release-summary-label">负责人</span>
            <span className="release-summary-value">{(histForStep[0]?.operator ?? getLoginDraft().user) || '—'}</span>
          </div>
          <div className="release-summary-item">
            <span className="release-summary-label">环境</span>
            <span className="release-summary-value">默认</span>
          </div>
        </div>
        {flowComplete && (
          <div className="release-complete-banner">
            该发布流程已全部完成，下方步骤仅可查看。
            <Button onClick={() => setViewStep(0)}>开启新变更</Button>
          </div>
        )}
      </Card>

      {/* 横向步骤条 */}
      <div className="release-steps">
        {STEPS.map((s, i) => {
          const done = doneMap[s.key]
          const failed = failedMap[s.key]
          const isCurrent = i === autoStep && !done
          const isViewing = i === viewStep
          const locked = !canSelect(i)
          return (
            <button
              key={s.key}
              type="button"
              className={`release-step${done ? ' done' : ''}${failed ? ' failed' : ''}${isCurrent ? ' current' : ''}${isViewing ? ' viewing' : ''}${locked ? ' locked' : ''}`}
              onClick={() => canSelect(i) && setViewStep(i)}
              title={locked ? s.lockedHint : undefined}
            >
              <span className="release-step-dot">{done ? '✓' : failed ? '✗' : i + 1}</span>
              <span className="release-step-name">{s.title}</span>
              {locked && <span className="release-step-lock">🔒</span>}
            </button>
          )
        })}
      </div>

      {/* 主内容 + 侧栏 */}
      <div className="release-layout">
        <div className="release-content">
          <Card title={`${cur.title}${latest && viewStep !== 0 ? ` · v${latest.version}` : ''}`}>
            {readOnly && (
              <div className="release-readonly-hint">只读：{cur.title} {doneMap[cur.key] ? '已完成' : '等待前置步骤'}，仅可查看结果与历史。</div>
            )}

            {viewStep === 0 && (
              <div className="release-draft-form">
                <Field label="系统提示词">
                  <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="新的系统提示词" style={{ minHeight: 90 }} disabled={readOnly} />
                </Field>
                <div className="grid cols-3" style={{ gap: 12 }}>
                  <Field label="模型">
                    <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="默认回落" disabled={readOnly} />
                  </Field>
                  <Field label="工具集（逗号分隔）">
                    <input value={tools} onChange={(e) => setTools(e.target.value)} disabled={readOnly} />
                  </Field>
                  <Field label="knowledge_version">
                    <input value={kv} onChange={(e) => setKv(e.target.value)} disabled={readOnly} />
                  </Field>
                </div>
                {!readOnly && (
                  <div className="row" style={{ gap: 8 }}>
                    <Button tone="primary" disabled={!prompt.trim() || !!busy} onClick={submitDraft}>创建版本</Button>
                    <Button onClick={importLastConfig}>导入上次配置</Button>
                    <Button onClick={loadTemplate}>从模板开始</Button>
                  </div>
                )}
                <p className="small muted mt">{readOnly ? '该流程已完成或等待前置，创建已锁定。' : '创建成功后会自动推进到「契约检查」。没有版本时这里是唯一的入口。'}</p>
              </div>
            )}

            {viewStep === 1 && (
              <div className="release-step-body">
                <p className="release-step-copy">
                  {contractSummary
                    ? `共 ${contractSummary.total} 项：通过 ${contractSummary.passed}，阻断 ${contractSummary.blocked}。`
                    : '运行契约检查，确认草稿满足发布契约。'}
                </p>
                {!readOnly && (
                  <div className="row" style={{ gap: 8 }}>
                    <Button tone="primary" disabled={!!busy || !draft || !canPublish} onClick={() => draft && onRunContract(draft.version)}>
                      运行契约检查
                    </Button>
                    {draft && <Button disabled={!!busy} onClick={() => onRunContract(draft.version)}>重试</Button>}
                  </div>
                )}
                {contractSummary && contractSummary.fails.length > 0 && (
                  <div className="release-result-list mt">
                    {contractSummary.fails.map((c) => (
                      <div key={c.id} className="release-result-item fail">
                        <b className="mono">{c.id}</b> <span>{c.reason}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {viewStep === 2 && (
              <div className="release-step-body">
                <p className="release-step-copy">
                  {regFor
                    ? `通过率 ${(regFor.data.pass_rate ?? 0) * 100}%${regFor.data.previous_pass_rate != null ? `（基线 ${(regFor.data.previous_pass_rate * 100).toFixed(0)}%）` : '（无基线）'}`
                    : '跑一次基准集回归，确认新草稿没有质量回退。'}
                </p>
                {!readOnly && (
                  <div className="row" style={{ gap: 8 }}>
                    <Button tone="primary" disabled={!!busy || !draft || !canPublish} onClick={() => draft && onRunRegression(draft.version)}>
                      {busy === `reg-${draft?.version}` ? '回归中…' : '运行回归'}
                    </Button>
                    {regFor && <Button onClick={onOpenWizard}>查看评测明细</Button>}
                  </div>
                )}
                {regFor && regFor.data.regressed && (
                  <div className="release-result-item fail mt">质量退化：建议返回草稿修改后重新跑评测。</div>
                )}
              </div>
            )}

            {viewStep === 3 && (
              <div className="release-step-body">
                <p className="release-step-copy">
                  {draft ? `把 v${draft.version} 放出小流量，验证真实指标。` : gray ? `灰度 v${gray.version} 已在进行中。` : '进入灰度，小流量验证。'}
                </p>
                {!readOnly && (
                  <div className="row" style={{ gap: 8 }}>
                    <Button tone="primary" disabled={!!busy || !draft || !canPublish} onClick={() => draft && onGray(draft.version)}>
                      开始灰度
                    </Button>
                    {gray && <Button disabled={canaryBusy || !!busy} onClick={() => onRunCanary(gray.version)}>刷新 Canary</Button>}
                  </div>
                )}
                {canary && (
                  <div className="release-result-list mt">
                    <div className="release-result-item"><b>样本</b> {canary.metrics.runs} 单</div>
                    <div className="release-result-item"><b>错误率</b> {canary.metrics.error_rate.toFixed(3)}</div>
                    <div className="release-result-item"><b>建议</b> {canary.action === 'stop' ? '暂停放量 / 回滚' : '可继续放量'}</div>
                  </div>
                )}
              </div>
            )}

            {viewStep === 4 && (
              <div className="release-step-body">
                <p className="release-step-copy">
                  {gray
                    ? `灰度 v${gray.version}：${canary ? (canary.action === 'stop' ? '指标恶化，建议回滚' : '指标健康，可全量发布') : '等待 Canary 数据'}`
                    : active
                      ? `v${active.version} 已全量上线。`
                      : '最终决定：全量发布或回滚。'}
                </p>
                {!readOnly && gray && (
                  <div className="row" style={{ gap: 8 }}>
                    <Button tone="primary" disabled={!!busy || !canPublish || (!!canary && canary.action === 'stop')} onClick={() => gray && onPublish(gray.version)}>
                      全量发布
                    </Button>
                    <Button tone="danger" disabled={!!busy} onClick={() => gray && onRollback(gray.version)}>回滚</Button>
                    <Button disabled={!!busy} onClick={() => gray && onHalt(gray.version)}>暂停</Button>
                  </div>
                )}
                {readOnly && active && (
                  <div className="row" style={{ gap: 8 }}>
                    <Button onClick={() => setViewStep(0)}>创建新版本</Button>
                  </div>
                )}
                <p className="small muted mt">全量发布 / 回滚 / 暂停都会二次确认，不会一键直出。</p>
              </div>
            )}

            <div className="release-next-advice">
              下一步建议：{readOnly ? (flowComplete ? '流程已完成，可回看或开启新变更' : '等待当前步骤完成') : failedMap[cur.key] ? '失败项修正后重试' : (STEPS[viewStep + 1] ? `通过后进入「${STEPS[viewStep + 1].title}」` : '全部走通，可以在线稳定运行')}
            </div>
          </Card>

          {/* 执行结果与历史 */}
          <Card title="执行结果与历史">
            {histForStep.length === 0 ? (
              <p className="small muted">这一步还没有执行记录。</p>
            ) : (
              <div className="release-history">
                {histForStep.map((e, i) => (
                  <div key={i} className={`release-history-item${e.ok ? '' : ' fail'}`}>
                    <div className="release-history-head">
                      <span className={`release-history-verdict${e.ok ? ' ok' : ' bad'}`}>{e.ok ? '✓' : '✗'}</span>
                      <span className="release-history-summary">{e.summary}</span>
                      <span className="small muted">{fmtTime(e.ts)}</span>
                      <span className="small muted">· {e.operator}</span>
                    </div>
                    {e.detail && <details className="small muted" style={{ marginTop: 6 }}><summary>查看明细</summary>{e.detail}</details>}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* 发布侧栏 */}
        <aside className="release-sidebar">
          <Card title="风险与权限">
            <div className="release-sidebar-block">
              <div className="small muted">发布权限</div>
              {canPublish ? (
                <div className="release-sidebar-ok">有权限，可以放行</div>
              ) : (
                <div className="release-sidebar-warn">无 release:publish 权限，发布会被后端拒绝。请管理员在「权限策略」授权。</div>
              )}
            </div>
            <div className="release-sidebar-block">
              <div className="small muted">灰度风险</div>
              {canary ? (
                canary.action === 'stop'
                  ? <div className="release-sidebar-warn">指标恶化（{canary.reasons.join('；')}），建议回滚</div>
                  : <div className="release-sidebar-ok">指标健康，可继续放量</div>
              ) : (
                <div className="release-sidebar-muted">暂无灰度 / 待评估</div>
              )}
            </div>
            <div className="release-sidebar-block">
              <div className="small muted">线上版本</div>
              <div className="release-sidebar-muted">{active ? `v${active.version} 运行中` : '尚未全量上线'}</div>
            </div>
          </Card>
          <Card title="快捷操作">
            <div className="release-sidebar-actions">
              <Link className="btn" to="/evaluation">看评测门禁</Link>
              <Link className="btn" to="/model">看模型健康</Link>
              <Button onClick={onOpenWizard} disabled={!pl.length || !!busy}>发布引导</Button>
              <Button disabled={!!busy} onClick={onChanged}>刷新数据</Button>
            </div>
          </Card>
        </aside>
      </div>
    </div>
  )
}
