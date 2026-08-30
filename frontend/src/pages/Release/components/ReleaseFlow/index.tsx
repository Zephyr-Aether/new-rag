import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, CanaryCheck, ContractCheck, Regression, Version } from '@/services'
import { Badge, Button, Card, Field, fmtTime } from '@/components'
import { Input } from '@/components/input'
import { Textarea } from '@/components/textarea'
import { Steps } from 'antd'
import { useConfirm } from '@/components/Confirm'
import { getLoginDraft } from '@/util'

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

const STEP_KEYS: StepKey[] = ['draft', 'contract', 'regression', 'gray', 'release']

/** 节点失败时展示的提示（区别于未解锁的 lockedHint）。 */
const FAIL_HINT: Partial<Record<StepKey, string>> = {
  contract: '契约未通过',
  regression: '回归退化',
}

/** 发布流阶段标识 → 中文。 */
const STATUS_LABEL: Record<string, string> = {
  empty: '尚未开始', draft: '草稿待验证', contract: '契约检查中', regression: '回归评测中',
  gray: '灰度放量中', release: '放量决策', done: '已上线', disabled: '已停用', terminated: '已终止',
}

const POLL_MS = 8000

interface ReleaseFlowProps {
  agentId: string
  versions: Version[] // 已按 version 倒序
  flowEpoch?: number // 变化时重新拉取发布流（创建新发布单后）
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
  flowEpoch,
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
  const { confirm, confirmEl } = useConfirm()
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
  const [history, setHistory] = useState<Partial<Record<StepKey, Exec[]>>>({})
  const latestDraftRef = useRef(latest?.version ?? -1)
  const prevLatestRef = useRef<string | undefined>(undefined)

  // —— 发布流配置（后端下发）：5 节点 code/name + 每节点 config 回显 + 阶段/终止标识 ——
  const [flow, setFlow] = useState<{ status: string; terminated: boolean; nodes: { code: string; name: string; config: Record<string, unknown> }[] } | null>(null)
  useEffect(() => {
    if (!agentId) return
    api.releaseFlow(agentId).then(setFlow).catch(() => undefined)
  }, [agentId, flowEpoch])
  const nodeNameByCode = useMemo(() => Object.fromEntries((flow?.nodes ?? []).map((n) => [n.code, n.name])), [flow])
  const flowTerminated = !!flow?.terminated
  const flowActive = !!flow && ['draft','contract','regression','gray','release'].includes(flow.status)
  const flowDraftCfg = (flow?.nodes.find((n) => n.code === 'draft')?.config ?? {}) as Record<string, unknown>
  function saveNode(code: string, config: Record<string, unknown>, status?: string) {
    api.releaseFlowNode(agentId, code, config, status).catch(() => undefined)
    setFlow((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        status: status ?? prev.status,
        // 推进状态即离开终止态（终态下创建草稿会隐式开启新一轮）
        terminated: status ? false : prev.terminated,
        nodes: prev.nodes.map((n) => (n.code === code ? { ...n, config } : n)),
      }
    })
  }
  async function onTerminate() {
    await api.releaseFlowTerminate(agentId)
    setFlow((prev) => (prev ? { ...prev, status: 'terminated', terminated: true } : prev))
  }

  /** 当前该操作的步骤：优先用后端下发的 current_step/status，未加载时本地推导。 */
  const localAuto = !latest ? 0 : latest.status === 'DRAFT' ? (passedRegression ? 3 : passedContract ? 2 : 1) : 4
  const FLOW_STEP: Record<string, number> = { empty: 0, draft: 1, contract: 1, regression: 2, gray: 3, release: 4, done: 4, disabled: 4 }
  const flowStep = flow && !flow.terminated ? (FLOW_STEP[flow.status] ?? 0) : null
  const autoStep = flowStep ?? localAuto
  /** 流程是否已全部走通：以后端 status 为准（done 才视为完成），未加载时按版本推导。 */
  const flowComplete = flow ? (flow.status === 'done' && !flow.terminated) : (hasActive && !draft && !hasGray)
  /** 是否有进行中的发布流（status 处于进行中阶段才轮询）。 */
  const inProgress = (flow ? flowActive : pl.length > 0) && !flowComplete
  /** 完成态（全走通 / 已终止）下仅草稿步可操作（创建新版本=开启新一轮），其余步骤只读。 */
  const viewOnly = flowComplete || flowTerminated

  // 阶段跟随：autoStep 变化时展示落到当前应做的一步（可前可后，如开启新变更回到草稿步）
  useEffect(() => {
    setViewStep(autoStep)
  }, [autoStep])

  function record(key: StepKey, summary: string, ok: boolean, detail?: string) {
    const rec: Exec = { ts: new Date().toISOString(), operator: getLoginDraft().user || '—', summary, ok, detail }
    setHistory((prev) => ({ ...prev, [key]: [rec, ...(prev[key] ?? [])].slice(0, 3) }))
    // 留痕入库：失败也不阻塞流程
    api.releaseFlowRecord(agentId, { version: latest?.version ?? 0, step: key, summary, ok, detail }).catch(() => undefined)
  }

  // 进入页面拉取发布流程历史（数据库）
  useEffect(() => {
    let alive = true
    api
      .releaseFlowHistory(agentId)
      .then((r) => {
        if (!alive) return
        const grouped: Partial<Record<StepKey, Exec[]>> = {}
        for (const rec of r.records) {
          const key = rec.step as StepKey
          if (!STEP_KEYS.includes(key)) continue
          grouped[key] = [...(grouped[key] ?? []), { ts: rec.created_at ?? '', operator: rec.operator, summary: rec.summary, ok: rec.ok, detail: rec.detail ?? undefined }]
        }
        for (const k of Object.keys(grouped)) grouped[k as StepKey] = (grouped[k as StepKey] ?? []).slice(0, 3)
        setHistory(grouped)
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [agentId])

  // 状态型动作（创建/灰度/发布）靠 refresh 带来的版本变化推进流程状态 + 留痕；展示步骤由 autoStep 驱动
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
      return
    }
    if (prevStatus && prevStatus !== latest.status) {
      if (latest.status === 'GRAY') { record('gray', `灰度放量 v${latest.version}`, true); saveNode('gray', { version: latest.version }, 'release') }
      else if (latest.status === 'ACTIVE') { record('release', `全量上线 v${latest.version}`, true); saveNode('release', { version: latest.version }, 'done') }
      else if (latest.status === 'DISABLED') record('release', `停用 / 回滚 v${latest.version}`, true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versions])

  // 报告型动作：契约/回归结果 → 推进 + 留痕
  useEffect(() => {
    if (!contractFor) return
    const passed = contractFor.data.checks.filter((c) => c.status === 'pass').length
    const failed = contractFor.data.checks.filter((c) => c.status === 'fail').length
    setPassedContract(!contractFor.data.blocked)
    record('contract', `v${contractFor.version} 契约检查：${passed} 通过 / ${failed} 失败`, !contractFor.data.blocked, contractFor.data.checks.filter((c) => c.status !== 'pass').map((c) => `${c.id}: ${c.reason}`).join('；') || undefined)
    saveNode('contract', { total: contractFor.data.checks.length, passed, failed }, contractFor.data.blocked ? 'contract' : 'regression')
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
    saveNode('regression', { pass_rate: regFor.data.pass_rate, regressed: regFor.data.regressed }, regFor.data.regressed ? 'regression' : 'gray')
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

  // 版本轮询：仅在有进行中的发布流时轮询；无版本 / 全走完时停止
  useEffect(() => {
    if (!inProgress) return
    const timer = setInterval(() => onChanged(), POLL_MS)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inProgress])

  // —— 步骤状态 ——
  const doneMap: Record<StepKey, boolean> = {
    draft: flowStep != null ? flowStep > 0 : pl.length > 0,
    contract: flowStep != null ? flowStep > 1 : (latest ? (latest.status === 'DRAFT' ? passedContract : true) : false),
    regression: flowStep != null ? flowStep > 2 : (latest ? (latest.status === 'DRAFT' ? passedRegression : true) : false),
    gray: flowStep != null ? flowStep > 3 : (latest ? (latest.status === 'GRAY' || latest.status === 'ACTIVE') : false),
    release: flowStep != null ? flowStep > 4 : (latest ? latest.status === 'ACTIVE' : false),
  }
  const failedMap: Record<StepKey, boolean> = {
    draft: false,
    contract: !!contractFor?.data.blocked,
    regression: !!regFor?.data.regressed,
    gray: false,
    release: false,
  }

  /** 门禁：上一步没做完，不能切到下一步；完成态可自由回看；新循环只能停在草稿步。 */
  function canSelect(i: number) {
    // 整个流程结束（完成/终止）：所有节点可点；进行中：只能点当前节点及之前的节点
    if (viewOnly) return true
    return i <= autoStep
  }

  /** 该步骤是否可以操作（否则只读）：进行中仅当前该做的一步；终态下只有草稿步可创建新版本（隐式开启新一轮）。 */
  function operable(i: number) {
    if (viewOnly) return i === 0
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
  /** 只读态展示用：优先用后端回显的 draft 节点 config，兜底取最新版本。 */
  const viewConfig = {
    prompt: String(flowDraftCfg.system_prompt ?? pl[0]?.config?.system_prompt ?? ''),
    model: String(flowDraftCfg.model ?? pl[0]?.config?.model ?? ''),
    tools: Array.isArray(flowDraftCfg.tools) ? (flowDraftCfg.tools as string[]).join(', ') : (Array.isArray(pl[0]?.config?.tools) ? (pl[0].config.tools as string[]).join(', ') : '—'),
    kv: String(flowDraftCfg.knowledge_version ?? pl[0]?.config?.knowledge_version ?? '—'),
  }
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
    saveNode('draft', { system_prompt: prompt.trim(), model: model.trim(), tools, kv: kv.trim() || '0' }, 'contract')
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
    <div className="grid" style={{ gap: 16 }}>
      {confirmEl}
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
        {flow && (
          <div className="release-stage-row">
            <span className="release-stage-label">当前阶段</span>
            <Badge status={flow.terminated ? 'FAIL' : 'OK'}>{STATUS_LABEL[flow.status] ?? flow.status}</Badge>
            {flowActive && (
              <Button
                tone="danger"
                onClick={() => confirm('终止发布', '确定终止当前发布流吗？之后所有步骤只能查看，不能继续操作。', () => void onTerminate(), { danger: true, confirmText: '终止' })}
              >
                终止发布
              </Button>
            )}
          </div>
        )}
        {flowTerminated && (
          <div className="release-terminated-banner">该发布流已终止。仅「创建草稿」步可操作，填好表单点「下一步」即自动开启新一轮。</div>
        )}
        {flowComplete && (
          <div className="release-complete-banner">该发布流程已全部完成。如需开启新变更，请在「创建草稿」步填好表单后点「下一步」。</div>
        )}
      </Card>

      {/* 横向步骤条（antd Steps） */}
      <Steps
        size="small"
        current={viewStep}
        onChange={(i) => canSelect(i) && setViewStep(i)}
        items={STEPS.map((s, i) => {
          const done = doneMap[s.key]
          const failed = failedMap[s.key]
          return {
            title: nodeNameByCode[s.key] ?? s.title,
            status: failed ? 'error' : flowTerminated ? 'wait' : flowComplete ? 'finish' : i === autoStep ? 'process' : done ? 'finish' : 'wait',
            description: failed ? FAIL_HINT[s.key] : undefined,
          }
        })}
      />

      {/* 主内容 + 侧栏 */}
      <div className="release-layout">
        <div className="release-content">
          <Card title={`${nodeNameByCode[cur.key] ?? cur.title}${latest && viewStep !== 0 ? ` · v${latest.version}` : ''}`}>
            {readOnly && (
              <div className="release-readonly-hint">只读：{cur.title} {flowTerminated ? '已终止' : flowComplete ? '已完成' : doneMap[cur.key] ? '已完成' : '等待前置步骤'}，仅可查看结果与历史。</div>
            )}

            {viewStep === 0 && (
              <div className="release-draft-form">
                <Field label="系统提示词">
                  <Textarea value={readOnly ? viewConfig.prompt : prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="新的系统提示词" className="min-h-[90px]" disabled={readOnly} />
                </Field>
                <div className="grid cols-3" style={{ gap: 12 }}>
                  <Field label="模型">
                    <Input value={readOnly ? viewConfig.model : model} onChange={(e) => setModel(e.target.value)} placeholder="默认回落" disabled={readOnly} />
                  </Field>
                  <Field label="工具集（逗号分隔）">
                    <Input value={readOnly ? viewConfig.tools : tools} onChange={(e) => setTools(e.target.value)} disabled={readOnly} />
                  </Field>
                  <Field label="knowledge_version">
                    <Input value={readOnly ? viewConfig.kv : kv} onChange={(e) => setKv(e.target.value)} disabled={readOnly} />
                  </Field>
                </div>
                {!readOnly && (
                  <div className="row" style={{ gap: 8 }}>
                    <Button tone="primary" disabled={!prompt.trim() || !!busy} onClick={submitDraft}>下一步</Button>
                    <Button onClick={importLastConfig}>导入上次配置</Button>
                    <Button onClick={loadTemplate}>从模板开始</Button>
                  </div>
                )}
                <p className="small muted mt">{readOnly ? '该流程已完成或等待前置，创建已锁定。' : '点击「下一步」会创建新草稿版本，并进入「契约检查」。没有版本时这里是唯一的入口。'}</p>
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
                    <Button tone="primary" disabled={!!busy || !draft} onClick={() => draft && onRunContract(draft.version)}>
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
                    <Button tone="primary" disabled={!!busy || !draft} onClick={() => draft && onRunRegression(draft.version)}>
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
                    <Button tone="primary" disabled={!!busy || !draft} onClick={() => draft && onGray(draft.version)}>
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
                <p className="small muted mt">全量发布 / 回滚 / 暂停都会二次确认，不会一键直出。</p>
              </div>
            )}

            {viewStep > 0 && (
              <div className="release-step-nav">
                <Button onClick={() => setViewStep(viewStep - 1)}>上一步</Button>
              </div>
            )}
            <div className="release-next-advice">
              下一步建议：{readOnly ? (flowComplete ? '流程已完成，可回看或开启新变更' : '等待当前步骤完成') : failedMap[cur.key] ? '失败项修正后重试' : (STEPS[viewStep + 1] ? `通过后进入「${STEPS[viewStep + 1].title}」` : '全部走通，可以在线稳定运行')}
            </div>
          </Card>

          {/* 执行结果与历史 */}
          <Card title="执行结果与历史" className="release-history-card">
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
