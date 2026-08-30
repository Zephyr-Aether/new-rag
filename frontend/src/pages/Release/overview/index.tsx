import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Steps } from 'antd'
import { api, ContractCheck, Regression, ReleaseOrder, Version } from '@/services'
import { Badge, Button, Card, Field, Loading, fmtTime } from '@/components'
import { Input } from '@/components/input'
import { Textarea } from '@/components/textarea'
import { EmptyState, FlowChain, PageHeader } from '@/components/Page'
import { useConfirm } from '@/components/Confirm'
import { usePermissions } from '@/hooks/usePermissions'
import GrayModal from '../components/GrayModal'
import ContractModal from '../components/ContractModal'
import RegressionModal from '../components/RegressionModal'
import { useMeta } from '../useMeta'
import { toast } from '@/toast'

const STATUS_LABEL: Record<string, string> = {
  empty: '尚未开始', draft: '草稿待验证', contract: '契约检查中', regression: '回归评测中',
  gray: '灰度放量中', release: '放量决策', done: '已上线', disabled: '已停用', terminated: '已终止',
}
const ORDER_STATUS: Record<string, { tone: string; label: string }> = {
  open: { tone: 'PROCESSING', label: '进行中' },
  done: { tone: 'OK', label: '已完成' },
  terminated: { tone: 'FAILED', label: '已终止' },
}
const STEPS = [
  { key: 'draft', title: '创建草稿' },
  { key: 'contract', title: '契约检查' },
  { key: 'regression', title: '回归评测' },
  { key: 'gray', title: '灰度放量' },
  { key: 'release', title: '全量发布' },
]
const FLOW_STEP: Record<string, number> = { empty: 0, draft: 1, contract: 1, regression: 2, gray: 3, release: 4, done: 4, disabled: 4 }

type FlowState = { status: string; terminated: boolean; nodes: { code: string; name: string; status: string; config?: Record<string, unknown> }[] }

export default function ReleaseOverview() {
  const { meta } = useMeta()
  const { confirm, confirmEl } = useConfirm()
  const { can } = usePermissions()
  const agentId = meta?.agent_id ?? ''

  const [flow, setFlow] = useState<FlowState | null>(null)
  const [orders, setOrders] = useState<ReleaseOrder[] | null>(null)
  const [versions, setVersions] = useState<Version[] | null>(null)
  const [contractFor, setContractFor] = useState<{ version: number; data: ContractCheck } | null>(null)
  const [regFor, setRegFor] = useState<{ version: number; data: Regression } | null>(null)
  const [grayFor, setGrayFor] = useState<number | null>(null)
  const [busy, setBusy] = useState('')

  // 草稿表单
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState('')
  const [tools, setTools] = useState('calc.add')
  const [kv, setKv] = useState('0')

  useEffect(() => {
    if (!agentId) return
    api.releaseFlow(agentId).then(setFlow).catch(() => undefined)
    api.releaseOrderList(agentId).then((o) => setOrders(o.orders)).catch(() => setOrders([]))
    api.versions(agentId).then((v) => setVersions(v.versions)).catch(() => setVersions([]))
  }, [agentId])

  const ordered = useMemo(() => (versions ? [...versions].sort((a, b) => b.version - a.version) : null), [versions])
  const draft = ordered?.find((v) => v.status === 'DRAFT') ?? null
  const gray = ordered?.find((v) => v.status === 'GRAY') ?? null
  const active = ordered?.find((v) => v.status === 'ACTIVE') ?? null

  const flowTerminated = !!flow?.terminated
  const flowComplete = flow ? flow.status === 'done' && !flow.terminated : false
  const flowStep = flow && !flow.terminated ? (FLOW_STEP[flow.status] ?? 0) : null
  const step = flowStep ?? 0
  const openOrder = (orders ?? []).find((o) => o.status === 'open') ?? null
  const latest = (orders ?? [])[0] ?? null
  const closedOrders = (orders ?? []).filter((o) => o.status !== 'open')

  const contractCfg = flow?.nodes.find((n) => n.code === 'contract')?.config ?? {}
  const regressionCfg = flow?.nodes.find((n) => n.code === 'regression')?.config ?? {}
  // 阻断态可从契约/回归结果即时判断，也可从节点 config（关单/刷新后）恢复
  const contractBlocked = contractFor?.data.blocked ?? Number(contractCfg.failed ?? 0) > 0
  const regressionBlocked = regFor?.data.regressed ?? !!regressionCfg.regressed
  const blocked = flowStep === 1 ? contractBlocked : flowStep === 2 ? regressionBlocked : false
  const needsManual = flowStep === 1 && !!contractFor && !contractFor.data.blocked && contractFor.data.needs_manual.length > 0
  const canPublish = can('release:publish')

  // —— 动作 ——
  function reload() {
    api.releaseFlow(agentId).then(setFlow).catch(() => undefined)
    api.versions(agentId).then((v) => setVersions(v.versions)).catch(() => undefined)
  }
  async function act(key: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(key)
    try {
      await fn()
      toast(ok)
      reload()
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setBusy('')
    }
  }
  async function createVersion() {
    if (!prompt.trim()) return
    await act('create', async () => {
      await api.createVersion(agentId, {
        system_prompt: prompt.trim(),
        model: model.trim() || undefined,
        config: { tools: tools.split(',').map((s) => s.trim()).filter(Boolean), knowledge_version: kv.trim() || '0' },
      })
      await api.releaseFlowNode(agentId, 'draft', { system_prompt: prompt.trim(), model: model.trim(), tools, kv: kv.trim() || '0' }, 'contract')
    }, '草稿版本已创建')
  }
  async function runContract(v: number) {
    setBusy(`contract-${v}`)
    try {
      const data = await api.contractCheck(agentId, v)
      setContractFor({ version: v, data })
      await api.releaseFlowNode(agentId, 'contract', { total: data.checks.length, passed: data.checks.filter((c) => c.status === 'pass').length, failed: data.checks.filter((c) => c.status === 'fail').length }, data.blocked ? 'contract' : 'regression')
      reload()
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setBusy('')
    }
  }
  async function runRegression(v: number) {
    setBusy(`reg-${v}`)
    try {
      const data = await api.regression(agentId, v)
      setRegFor({ version: v, data })
      await api.releaseFlowNode(agentId, 'regression', { pass_rate: data.pass_rate, regressed: data.regressed }, data.regressed ? 'regression' : 'gray')
      reload()
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setBusy('')
    }
  }
  function importLastConfig() {
    const cfg = ordered?.find((v) => v.status !== 'DRAFT')?.config
    if (!cfg) return
    setPrompt(String(cfg.system_prompt ?? ''))
    setModel(String(cfg.model ?? ''))
    setTools(Array.isArray(cfg.tools) ? (cfg.tools as string[]).join(', ') : 'calc.add')
    setKv(String(cfg.knowledge_version ?? '0'))
  }

  if (!meta) return <Loading />

  // —— 步骤条状态 ——
  const stepsItems: { title: string; status: 'wait' | 'process' | 'finish' | 'error' }[] = STEPS.map((s, i) => {
    const done = flowStep != null && i < flowStep
    const failed = (s.key === 'contract' && contractBlocked) || (s.key === 'regression' && regressionBlocked)
    return {
      title: s.title,
      status: failed ? 'error' : flowTerminated ? 'wait' : flowComplete ? 'finish' : done ? 'finish' : i === step ? 'process' : 'wait',
    }
  })
  const target = draft ?? gray ?? active ?? null

  return (
    <div className="grid" style={{ gap: 16 }}>
      {confirmEl}
      <FlowChain current="release" />
      <PageHeader title="发布" desc="当前发布操作台：一眼看清进度、下一步动作与风险。" />

      {/* 空态：没有进行中的发布单 */}
      {!openOrder && (
        <Card className="release-overview-empty">
          <EmptyState
            title={latest ? '没有进行中的发布单' : '尚未创建发布单'}
            desc="创建发布单，进入正式的发布流程（草稿 → 契约 → 回归 → 灰度 → 上线）。"
            actions={<Button asChild tone="primary"><Link to="/release/orders/new">创建发布单</Link></Button>}
          />
        </Card>
      )}

      {openOrder && !flow && <Loading />}

      {openOrder && flow && (
        <>
          {/* 当前状态卡 */}
          <Card title="当前发布">
            <div className="release-summary">
              <div className="release-summary-item">
                <span className="release-summary-label">发布单号</span>
                <span className="release-summary-value mono">{openOrder ? `#${openOrder.order_no}` : '—'}</span>
              </div>
              <div className="release-summary-item">
                <span className="release-summary-label">目标版本</span>
                <span className="release-summary-value">{target ? `v${target.version}` : '待创建'}</span>
              </div>
              <div className="release-summary-item">
                <span className="release-summary-label">当前步骤</span>
                <span className="release-summary-value">{flowComplete || flowTerminated ? STATUS_LABEL[flow.status] ?? flow.status : STEPS[step]?.title}</span>
              </div>
              <div className="release-summary-item">
                <span className="release-summary-label">发布状态</span>
                <span className="release-summary-value">
                  <Badge status={flowTerminated ? 'FAILED' : blocked ? 'FAILED' : flowComplete ? 'OK' : 'PROCESSING'}>
                    {blocked ? '已阻断' : STATUS_LABEL[flow.status] ?? flow.status}
                  </Badge>
                </span>
              </div>
            </div>

            <Steps size="small" current={step} items={stepsItems} />

            <div className="release-overview-action">
              {blocked ? (
                <Button asChild tone="danger"><Link to={`/release/orders/${openOrder.id}`}>处理阻断</Link></Button>
              ) : (
                <Button asChild tone="primary"><Link to={`/release/orders/${openOrder.id}`}>继续当前发布 · 发布单 #{openOrder.order_no}</Link></Button>
              )}
            </div>
          </Card>

          {/* 当前步任务卡 */}
          {!flowComplete && !flowTerminated && (
            <Card title={`当前步 · ${STEPS[step]?.title}`} className="release-current-step">
              {step === 0 && (
                <div className="release-draft-form">
                  <Field label="系统提示词">
                    <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="新的系统提示词" className="min-h-[90px]" />
                  </Field>
                  <div className="grid cols-3" style={{ gap: 12 }}>
                    <Field label="模型">
                      <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="默认回落" />
                    </Field>
                    <Field label="工具集（逗号分隔）">
                      <Input value={tools} onChange={(e) => setTools(e.target.value)} />
                    </Field>
                    <Field label="knowledge_version">
                      <Input value={kv} onChange={(e) => setKv(e.target.value)} />
                    </Field>
                  </div>
                  <div className="row" style={{ gap: 8 }}>
                    <Button tone="primary" disabled={!prompt.trim() || !!busy} onClick={() => void createVersion()}>
                      {busy === 'create' ? '创建中…' : '创建版本'}
                    </Button>
                    <Button onClick={importLastConfig}>导入上次配置</Button>
                  </div>
                  <p className="small muted mt">创建草稿版本后自动进入「契约检查」。</p>
                </div>
              )}

              {step === 1 && (
                <div className="release-step-body">
                  <p className="release-step-copy">
                    {contractFor
                      ? `共 ${contractFor.data.checks.length} 项：通过 ${contractFor.data.checks.filter((c) => c.status === 'pass').length}，阻断 ${contractFor.data.checks.filter((c) => c.status === 'fail').length}。`
                      : '运行契约检查，确认草稿满足发布契约。'}
                  </p>
                  <div className="row" style={{ gap: 8 }}>
                    <Button tone="primary" disabled={!!busy || !draft} onClick={() => draft && runContract(draft.version)}>
                      {busy === `contract-${draft?.version}` ? '检查中…' : '运行契约检查'}
                    </Button>
                  </div>
                  {contractFor && <ResultBox state={blocked ? 'blocked' : needsManual ? 'manual' : 'ok'} blockedReason={contractFor.data.checks.filter((c) => c.status === 'fail').map((c) => `${c.id}: ${c.reason}`)} okText={`契约通过，进入「回归评测」`} manualText={`有人工签核项：${contractFor.data.needs_manual.join('、')}，需确认后继续`} />}
                </div>
              )}

              {step === 2 && (
                <div className="release-step-body">
                  <p className="release-step-copy">
                    {regFor
                      ? `通过率 ${(regFor.data.pass_rate ?? 0) * 100}%${regFor.data.previous_pass_rate != null ? `（基线 ${(regFor.data.previous_pass_rate * 100).toFixed(0)}%）` : '（无基线）'}`
                      : '跑一次基准集回归，确认新草稿没有质量回退。'}
                  </p>
                  <div className="row" style={{ gap: 8 }}>
                    <Button tone="primary" disabled={!!busy || !draft} onClick={() => draft && runRegression(draft.version)}>
                      {busy === `reg-${draft?.version}` ? '回归中…' : '运行回归'}
                    </Button>
                  </div>
                  {regFor && <ResultBox state={regFor.data.regressed ? 'blocked' : 'ok'} blockedReason={['质量退化：建议返回草稿修改后重新评测']} okText={`回归通过，进入「灰度放量」`} />}
                </div>
              )}

              {step === 3 && (
                <div className="release-step-body">
                  <p className="release-step-copy">
                    {draft ? `把 v${draft.version} 放出小流量，验证真实指标。` : gray ? `灰度 v${gray.version} 已在进行中。` : '进入灰度，小流量验证。'}
                  </p>
                  <div className="row" style={{ gap: 8 }}>
                    <Button tone="primary" disabled={!!busy || !draft} onClick={() => draft && setGrayFor(draft.version)}>
                      设置灰度
                    </Button>
                  </div>
                </div>
              )}

              {step === 4 && (
                <div className="release-step-body">
                  <p className="release-step-copy">
                    {gray ? `灰度 v${gray.version} 已放量，确认健康后可全量发布。` : active ? `v${active.version} 已全量上线。` : '最终决定：全量发布。'}
                  </p>
                  <div className="row" style={{ gap: 8 }}>
                    <Button tone="primary" disabled={!!busy || !canPublish || !(gray || active)} onClick={() => (gray ?? active) && act('pub', async () => {
                      const v = (gray ?? active)!.version
                      await api.publish(agentId, v)
                      await api.releaseFlowNode(agentId, 'release', { version: v }, 'done')
                    }, '已全量发布')}>
                      全量发布
                    </Button>
                  </div>
                </div>
              )}
            </Card>
          )}

          {flowComplete && (
            <Card className="release-complete-banner">
              该发布单已全部完成（已上线）。如需开启新变更，请创建新的发布单。
            </Card>
          )}
          {flowTerminated && (
            <Card className="release-terminated-banner">
              当前发布单已终止。如需重新发布，请创建新的发布单。
            </Card>
          )}

          {/* 危险操作收纳 */}
          {(openOrder || target) && (
            <details className="release-details">
              <summary>更多操作（危险）</summary>
              <Card className="mt">
                <div className="row" style={{ gap: 8 }}>
                  <Button tone="danger" disabled={!!busy} onClick={() => confirm('终止发布', '确定终止当前发布单吗？之后所有步骤只能查看。', () => act('terminate', () => api.releaseFlowTerminate(agentId), '已终止发布'), { danger: true, confirmText: '终止' })}>
                    终止当前发布
                  </Button>
                  {target && (
                    <Button tone="danger" disabled={!!busy} onClick={() => confirm('回滚版本', `确定回滚 v${target.version} 吗？当前版本将停止、流量切换。`, () => act(`rb`, () => api.rollback(agentId), '已回滚'), { danger: true, confirmText: '回滚' })}>
                      回滚
                    </Button>
                  )}
                </div>
              </Card>
            </details>
          )}
        </>
      )}

      {/* 历史发布单（折叠，只含已关单） */}
      {!flow && orders === null && <Loading />}
      {closedOrders.length > 0 && (
        <details className="release-details">
          <summary>历史发布单（最近 {Math.min(3, closedOrders.length)} 条）</summary>
          <Card className="mt">
            <div className="release-order-list">
              {closedOrders.slice(0, 3).map((o) => {
                const st = ORDER_STATUS[o.status] ?? { tone: 'slate', label: o.status }
                return (
                  <div key={o.id} className="release-order-row">
                    <b className="mono">#{o.order_no}</b>
                    <Badge status={st.tone}>{st.label}</Badge>
                    {o.summary && <span className="mono small">{o.summary}</span>}
                    <span className="small muted">{o.created_by || '—'}</span>
                    <span className="small muted">{o.created_at ? fmtTime(o.created_at) : '—'}</span>
                    <span className="spacer" />
                    <Button asChild><Link to={`/release/orders/${o.id}`}>查看详情</Link></Button>
                  </div>
                )
              })}
            </div>
            {closedOrders.length > 3 && (
              <p className="small mt" style={{ textAlign: 'right' }}>
                <Link to="/release/orders">查看全部（共 {closedOrders.length} 张）→</Link>
              </p>
            )}
          </Card>
        </details>
      )}

      {grayFor !== null && (
        <GrayModal
          version={grayFor}
          onClose={() => setGrayFor(null)}
          onSubmit={async (pct) => {
            await act(`gray-${grayFor}`, async () => {
              await api.gray(agentId, grayFor, pct)
              await api.releaseFlowNode(agentId, 'gray', { version: grayFor }, 'release')
            }, `v${grayFor} 灰度 ${pct}%`)
            setGrayFor(null)
          }}
        />
      )}
      {contractFor && (
        <ContractModal data={contractFor.data} onClose={() => setContractFor(null)} />
      )}
      {regFor && (
        <RegressionModal version={regFor.version} data={regFor.data} onClose={() => setRegFor(null)} />
      )}
    </div>
  )
}

/** 当前步结果区：可继续 / 需人工确认 / 已阻断。 */
function ResultBox({ state, blockedReason = [], okText, manualText }: { state: 'ok' | 'manual' | 'blocked'; blockedReason?: string[]; okText?: string; manualText?: string }) {
  if (state === 'blocked') {
    return (
      <div className="release-result-item fail mt">
        <b>已阻断</b>
        {blockedReason.map((r, i) => (
          <div key={i} className="small muted" style={{ marginTop: 4 }}>{r}</div>
        ))}
        <div className="small mt">下一步建议：修正后重试；如确认无误，可在详情页强制继续。</div>
      </div>
    )
  }
  if (state === 'manual') {
    return (
      <div className="release-result-item mt">
        <b>需人工确认</b>
        <div className="small muted" style={{ marginTop: 4 }}>{manualText}</div>
      </div>
    )
  }
  return (
    <div className="release-result-item ok mt">
      <b>可继续</b>
      <span className="small muted"> {okText}</span>
    </div>
  )
}
