import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, CanaryCheck, ContractCheck, Meta, Regression, ReleaseMetrics, Version } from '../api'
import { Badge, Bar, Button, Card, ErrorBox, Field, fmtCost, fmtTime, Loading, Modal, SuccessBox, TableSkeleton } from '../components/ui'
import { EmptyState, PageError } from '../components/Page'
import ReleaseWizard from './ReleaseWizard'
import { toast } from '../toast'
import { useConfirm } from '../components/Confirm'
import { usePermissions } from '../hooks/usePermissions'
import { PageHeader } from '../components/Page'

function ReleaseDecision({
  agentId,
  versions,
  canPublish,
  onChanged,
  onCreate,
  onOpenWizard,
}: {
  agentId: string
  versions: Version[]
  canPublish: boolean
  onChanged: () => void
  onCreate: () => void
  onOpenWizard: () => void
}) {
  const gray = versions.filter((v) => v.status === 'GRAY').sort((a, b) => b.version - a.version)[0]
  const active = versions.find((v) => v.status === 'ACTIVE')
  const drafts = versions.filter((v) => v.status === 'DRAFT').sort((a, b) => b.version - a.version)
  const latestDraft = drafts[0]
  const { confirm, confirmEl } = useConfirm()
  const [canary, setCanary] = useState<CanaryCheck | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!gray) {
      setCanary(null)
      return
    }
    setBusy(true)
    api
      .canaryEvaluate(agentId)
      .then(setCanary)
      .catch(() => setCanary(null))
      .finally(() => setBusy(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, gray?.version])

  async function act2(fn: () => Promise<unknown>, ok: string) {
    setBusy(true)
    try {
      await fn()
      toast(ok)
      onChanged()
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setBusy(false)
    }
  }

  const m = canary?.metrics
  const recommendStop = canary?.action === 'stop'
  const summary = (() => {
    if (gray) {
      if (busy && !canary) {
        return {
          badge: 'WARN',
          title: `灰度 v${gray.version} 正在等待 Canary 结果`,
          note: '先继续收集运行样本，等指标稳定后再决定是否放量。',
          blockers: ['灰度指标仍在评估中'],
        }
      }
      if (!canary) {
        return {
          badge: 'WARN',
          title: `灰度 v${gray.version} 还没有足够的判断数据`,
          note: '先跑几次真实任务，让错误率、延迟和工具成功率形成有效样本。',
          blockers: ['暂无灰度运行数据'],
        }
      }
      if (recommendStop) {
        return {
          badge: 'FAIL',
          title: `灰度 v${gray.version} 指标恶化，建议先回滚`,
          note: canary.reasons.join('；') || '当前灰度结果不适合继续放量。',
          blockers: canary.reasons.length > 0 ? canary.reasons : ['Canary 未通过'],
        }
      }
      return {
        badge: 'PASSED',
        title: `灰度 v${gray.version} 指标健康，可以继续放量`,
        note: canary.reasons.join('；') || 'Canary 已通过，接下来更适合转全量发布。',
        blockers: [],
      }
    }

    if (latestDraft) {
      return {
        badge: 'DRAFT',
        title: `有 ${drafts.length} 个草稿版本待验证`,
        note: `优先从 v${latestDraft.version} 开始做契约检查和回归评测，确认通过后再进入灰度。`,
        blockers: canPublish ? ['尚未进入灰度'] : ['当前账号没有发布权限'],
      }
    }

    if (active) {
      return {
        badge: 'ACTIVE',
        title: `当前线上运行 v${active.version}`,
        note: '目前没有正在灰度的版本，线上相对稳定。需要改动时，先创建新版本再沿发布链路推进。',
        blockers: canPublish ? [] : ['当前账号没有发布权限'],
      }
    }

    return {
      badge: 'DRAFT',
      title: '还没有可生效的版本',
      note: '先创建第一个版本，再补齐评测、灰度和发布动作，平台才有可回退的交付历史。',
      blockers: canPublish ? ['尚未创建版本'] : ['当前账号没有发布权限'],
    }
  })()

  return (
    <>
      {confirmEl}
      <Card title="当前发布判断">
        <div className="decision-panel">
          <div className="decision-main">
            <div className="row" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              <Badge status={summary.badge} />
              <div className="decision-title">{summary.title}</div>
            </div>
            <div className="decision-note">{summary.note}</div>
            {summary.blockers.length > 0 && (
              <div className="decision-list">
                {summary.blockers.map((item) => (
                  <span key={item} className="decision-chip">{item}</span>
                ))}
              </div>
            )}
            <div className="row mt" style={{ flexWrap: 'wrap' }}>
              {!gray ? (
                <>
                  <Button tone="primary" onClick={onCreate} disabled={busy}>创建版本</Button>
                  <Button onClick={onOpenWizard} disabled={!versions.length || busy}>发布引导</Button>
                </>
              ) : canary === null ? (
                <Button disabled={busy} onClick={() => act2(() => api.canaryEvaluate(agentId).then(setCanary), '已刷新灰度判断')}>
                  刷新 Canary
                </Button>
              ) : recommendStop ? (
                <>
                  <Button tone="danger" disabled={busy} onClick={() => confirm('停用灰度', `确定停用 v${gray.version} 灰度吗？新流量将回落 ACTIVE。`, () => act2(() => api.halt(agentId, gray.version), `v${gray.version} 已停用灰度`), { danger: true, confirmText: '停用' })}>
                    停用灰度
                  </Button>
                  <Button disabled={busy} onClick={() => confirm('回滚灰度', `确定回滚 v${gray.version} 吗？将回滚到基准 ACTIVE 版本。`, () => act2(() => api.rollback(agentId, gray.version), `已回滚到 v${gray.version}`), { danger: true, confirmText: '回滚' })}>
                    回滚
                  </Button>
                </>
              ) : (
                <Button tone="primary" disabled={busy} onClick={() => act2(() => api.publish(agentId, gray.version), `v${gray.version} 已全量发布`)}>
                  全量发布
                </Button>
              )}
              <Link className="btn" to="/evaluation">
                看评测门禁
              </Link>
              <Link className="btn" to="/model">
                看模型健康
              </Link>
            </div>
          </div>

          <div className="decision-side">
            <div className="decision-meta-row">
              <span className="decision-meta-label">当前生效</span>
              <span className="decision-meta-value">{active ? `v${active.version}` : '—'}</span>
            </div>
            <div className="decision-meta-row">
              <span className="decision-meta-label">灰度版本</span>
              <span className="decision-meta-value">{gray ? `v${gray.version}` : '暂无'}</span>
            </div>
            <div className="decision-meta-row">
              <span className="decision-meta-label">草稿版本</span>
              <span className="decision-meta-value">{drafts.length > 0 ? `${drafts.length} 个` : '暂无'}</span>
            </div>
            <div className="decision-meta-row">
              <span className="decision-meta-label">Canary 样本</span>
              <span className="decision-meta-value">{m ? `${m.runs} 单` : '待生成'}</span>
            </div>
            {m && (
              <>
                <div className="decision-meta-row">
                  <span className="decision-meta-label">错误率</span>
                  <span className="decision-meta-value">{m.error_rate.toFixed(2)}</span>
                </div>
                <div className="decision-meta-row">
                  <span className="decision-meta-label">平均延迟</span>
                  <span className="decision-meta-value">{m.avg_latency_s.toFixed(1)}s</span>
                </div>
              </>
            )}
          </div>
        </div>
      </Card>
    </>
  )
}

const NEXT_ACTION: Record<string, string> = {
  DRAFT: '跑契约+回归 → 发布',
  ACTIVE: '创建新版本 或 灰度',
  GRAY: 'canary 检查 → 升级发布',
  DISABLED: '重新发布',
}

export default function Release() {
  const { confirm, confirmEl } = useConfirm()
  const { can } = usePermissions()
  const [meta, setMeta] = useState<Meta | null>(null)
  const [versions, setVersions] = useState<Version[] | null>(null)
  const [metrics, setMetrics] = useState<ReleaseMetrics[] | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)

  // 弹窗
  const [createOpen, setCreateOpen] = useState(false)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [contractFor, setContractFor] = useState<{ version: number; data: ContractCheck } | null>(null)
  const [regFor, setRegFor] = useState<{ version: number; data: Regression } | null>(null)
  const [grayFor, setGrayFor] = useState<number | null>(null)
  const [canaryFor, setCanaryFor] = useState<{ version: number; data: CanaryCheck } | null>(null)

  const agentId = meta?.agent_id ?? ''
  const orderedVersions = versions ? [...versions].sort((a, b) => b.version - a.version) : null

  const refresh = useCallback(async () => {
    if (!agentId) return
    const [v, m] = await Promise.all([api.versions(agentId), api.releaseMetrics(agentId)])
    setVersions(v.versions)
    setMetrics(m.metrics)
  }, [agentId])

  useEffect(() => {
    api.meta().then(setMeta).catch((e: Error) => setErr(e.message))
  }, [])
  useEffect(() => {
    refresh().catch((e: Error) => setErr(e.message))
  }, [refresh])

  async function act(key: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(key)
    setErr('')
    try {
      await fn()
      toast(ok)
      setNotice({ kind: 'success', text: ok })
      await refresh()
    } catch (e) {
      const message = (e as Error).message
      toast(message, 'err')
      setNotice({ kind: 'error', text: message })
    } finally {
      setBusy('')
    }
  }

  async function runContract(v: number) {
    setBusy(`contract-${v}`)
    try {
      const data = await api.contractCheck(agentId, v)
      setContractFor({ version: v, data })
      setNotice({ kind: 'success', text: `v${v} 契约检查已完成，结果已打开。` })
    } catch (e) {
      const message = (e as Error).message
      toast(message, 'err')
      setNotice({ kind: 'error', text: message })
    } finally {
      setBusy('')
    }
  }

  async function runSecurity(v: number) {
    setBusy(`sec-${v}`)
    try {
      const r = await api.securityEval(agentId, v)
      const message = `v${v} 安全评测：${r.passed}/${r.total} 未被利用（pass_rate ${r.pass_rate.toFixed(2)}）`
      toast(message)
      setNotice({ kind: 'success', text: message })
    } catch (e) {
      const message = (e as Error).message
      toast(message, 'err')
      setNotice({ kind: 'error', text: message })
    } finally {
      setBusy('')
    }
  }

  async function runRegression(v: number) {
    setBusy(`reg-${v}`)
    try {
      const data = await api.regression(agentId, v) // §20 基准集回归报告（pass_rate vs 上一版本）
      setRegFor({ version: v, data })
      setNotice({ kind: 'success', text: `v${v} 回归报告已生成，结果已打开。` })
    } catch (e) {
      const message = (e as Error).message
      toast(message, 'err')
      setNotice({ kind: 'error', text: message })
    } finally {
      setBusy('')
    }
  }

  async function runCanary(v: number) {
    setBusy(`canary-${v}`)
    try {
      const data = await api.canaryEvaluate(agentId)  // §57 对当前 GRAY 版本做 canary 检查
      setCanaryFor({ version: v, data })
      setNotice({ kind: 'success', text: `v${v} Canary 检查已完成，结果已打开。` })
    } catch (e) {
      const message = (e as Error).message
      toast(message, 'err')
      setNotice({ kind: 'error', text: message })
    } finally {
      setBusy('')
    }
  }

  if (!meta) return err ? <PageError message={err} retry={() => refresh().catch((e: Error) => setErr(e.message))} /> : <Loading />

  return (
    <div className="grid" style={{ gap: 18 }}>
      {confirmEl}
      {err && <PageError message={err} retry={() => refresh().catch((e: Error) => setErr(e.message))} />}

      <PageHeader
        title="版本发布"
        desc="先看当前版本能不能动，再走创建、验证、灰度和全量发布。"
        actions={
          <>
            <Button tone="primary" disabled={!orderedVersions || orderedVersions.length === 0} onClick={() => setWizardOpen(true)}>
              发布引导
            </Button>
            <Button tone="primary" onClick={() => setCreateOpen(true)}>
              创建版本
            </Button>
          </>
        }
      />

      {!can('release:publish') && (
        <div style={{ background: '#fffbeb', border: '1px solid #fcd34d', color: '#92400e', borderRadius: 8, padding: '10px 12px' }}>
          审批门禁：当前账号没有 <code>release:publish</code> 权限，发布会被后端拒绝。请管理员在「权限策略」中为你的角色授权发布，或走既有审批流程。
        </div>
      )}

      {notice && (
        <div className="mb">
          {notice.kind === 'success' ? <SuccessBox message={notice.text} /> : <ErrorBox message={notice.text} />}
        </div>
      )}

      <ReleaseDecision
        agentId={agentId}
        versions={orderedVersions ?? []}
        canPublish={can('release:publish')}
        onChanged={() => refresh().catch((e: Error) => setErr(e.message))}
        onCreate={() => setCreateOpen(true)}
        onOpenWizard={() => setWizardOpen(true)}
      />

      <Card title={`版本目录（${orderedVersions?.length ?? '…'}）`}>
        {orderedVersions === null ? (
          <TableSkeleton rows={5} cols={5} />
        ) : orderedVersions.length === 0 ? (
          <EmptyState
            title="还没有版本"
            desc="先创建第一个版本，再进入灰度和放量，Agent 行为变更才有可回退的历史。"
            actionLabel="创建版本"
            action={() => setCreateOpen(true)}
          />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>版本</th>
                <th>状态</th>
                <th>模型</th>
                <th>时间</th>
                <th>下一步</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {orderedVersions.map((v) => {
                const tools = Array.isArray(v.config.tools) ? (v.config.tools as string[]).join(', ') : '—'
                const kv = v.config.knowledge_version ?? '—'
                return (
                  <tr key={v.version}>
                    <td className="mono">v{v.version}</td>
                    <td>
                      <Badge status={v.status} />
                    </td>
                    <td>
                      <div className="recent-main">
                        <div className="recent-title mono small">{v.model || '默认'}</div>
                        <div className="recent-sub">tools: {tools || '—'} · knowledge {String(kv)}</div>
                      </div>
                    </td>
                    <td className="mono small muted">{fmtTime(v.created_at)}</td>
                    <td className="small muted">{NEXT_ACTION[v.status] ?? '—'}</td>
                    <td>
                      <div className="row" style={{ gap: 6 }}>
                        <Button disabled={busy === `pub-${v.version}`} onClick={() => act(`pub-${v.version}`, () => api.publish(agentId, v.version), `v${v.version} 已发布`)}>
                          发布
                        </Button>
                        <Button disabled={busy === `gray-${v.version}`} onClick={() => setGrayFor(v.version)}>
                          灰度
                        </Button>
                        {v.status === 'GRAY' && (
                          <Button disabled={busy === `canary-${v.version}`} onClick={() => runCanary(v.version)}>
                            Canary
                          </Button>
                        )}
                        <Button disabled={busy === `rb-${v.version}`} onClick={() => confirm('回滚版本', `确定回滚到 v${v.version} 吗？当前 ACTIVE 会被降级为 DISABLED。`, () => act(`rb-${v.version}`, () => api.rollback(agentId, v.version), `已回滚到 v${v.version}`), { danger: true, confirmText: '回滚' })}>
                          回滚
                        </Button>
                        <Button disabled={busy === `halt-${v.version}`} onClick={() => confirm('停用版本', `确定停用 v${v.version} 吗？该版本将不再生效。`, () => act(`halt-${v.version}`, () => api.halt(agentId, v.version), `v${v.version} 已停用`), { danger: true, confirmText: '停用' })}>
                          停用
                        </Button>
                        <Button disabled={busy === `contract-${v.version}`} onClick={() => runContract(v.version)}>
                          契约
                        </Button>
                        <Button disabled={busy === `reg-${v.version}`} onClick={() => runRegression(v.version)}>
                          {busy === `reg-${v.version}` ? '回归中…' : '回归'}
                        </Button>
                        <Button disabled={busy === `sec-${v.version}`} onClick={() => runSecurity(v.version)}>
                          安全评测
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="版本效果">
        {metrics === null ? (
          <TableSkeleton rows={5} cols={5} />
        ) : metrics.length === 0 ? (
          <EmptyState
            title="该版本还没有运行数据"
            desc="发布后先跑几次任务，这里才会逐步出现错误率、成本和反馈等效果指标。"
          />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>版本</th>
                <th>状态</th>
                <th className="num">runs</th>
                <th className="num">错误率</th>
                <th className="num">成本</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m, i) => (
                <tr key={i}>
                  <td className="mono">v{m.version}</td>
                  <td>
                    <Badge status={m.release_status} />
                  </td>
                  <td className="num">{m.runs}</td>
                  <td className="num">
                    <div className="row" style={{ gap: 8 }}>
                      <Bar value={m.error_rate} />
                      <span className="mono">{m.error_rate.toFixed(3)}</span>
                    </div>
                  </td>
                  <td className="num mono">{fmtCost(m.cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {createOpen && (
        <CreateVersionModal
          onClose={() => setCreateOpen(false)}
          onSubmit={async (body) => {
            await act('create', () => api.createVersion(agentId, body), '版本已创建')
            setCreateOpen(false)
          }}
        />
      )}

      {grayFor !== null && (
        <GrayModal
          version={grayFor}
          onClose={() => setGrayFor(null)}
          onSubmit={async (pct) => {
            await act(`gray-${grayFor}`, () => api.gray(agentId, grayFor, pct), `v${grayFor} 灰度 ${pct}%`)
            setGrayFor(null)
          }}
        />
      )}

      {regFor && (
        <RegressionModal version={regFor.version} data={regFor.data} onClose={() => setRegFor(null)} />
      )}

      {contractFor && (
        <ContractModal
          data={contractFor.data}
          onClose={() => setContractFor(null)}
          onEvaluate={async () => {
            await act(`eval-${contractFor.version}`, () => api.publish(agentId, contractFor.version, false, true), `v${contractFor.version} 已过回归并发布`)
            setContractFor(null)
          }}
        />
      )}

      {canaryFor && (
        <CanaryModal
          version={canaryFor.version}
          data={canaryFor.data}
          onClose={() => setCanaryFor(null)}
          onHalt={() =>
            confirm('停用灰度', `确定停用 v${canaryFor.version} 灰度吗？新流量将回落 ACTIVE 版本。`, async () => {
              await act(`halt-${canaryFor.version}`, () => api.halt(agentId, canaryFor.version), `v${canaryFor.version} 已停用`)
              setCanaryFor(null)
            }, { danger: true, confirmText: '停用灰度' })
          }
          onRollback={() =>
            confirm('回滚版本', `确定回滚到 v${canaryFor.version} 吗？当前版本将停止、流量切到目标版本。`, async () => {
              await act(`rb-${canaryFor.version}`, () => api.rollback(agentId, canaryFor.version), `已回滚到 v${canaryFor.version}`)
              setCanaryFor(null)
            }, { danger: true, confirmText: '回滚' })
          }
        />
      )}

      {wizardOpen && versions !== null && (
        <ReleaseWizard
          agentId={agentId}
          versions={versions}
          onClose={() => setWizardOpen(false)}
          onDone={() => {
            setWizardOpen(false)
            refresh().catch((e: Error) => setErr(e.message))
          }}
        />
      )}
    </div>
  )
}

function CreateVersionModal({
  onClose,
  onSubmit,
}: {
  onClose: () => void
  onSubmit: (body: { system_prompt: string; model?: string; config?: Record<string, unknown> }) => void
}) {
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState('')
  const [tools, setTools] = useState('calc.add')
  const [kv, setKv] = useState('0')
  return (
    <Modal title="创建新版本" onClose={onClose}>
      <Field label="System Prompt">
        <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="新的系统提示词" />
      </Field>
      <Field label="模型（可选，默认回落）">
        <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="mock-model" />
      </Field>
      <Field label="工具集（逗号分隔）">
        <input value={tools} onChange={(e) => setTools(e.target.value)} />
      </Field>
      <Field label="knowledge_version">
        <input value={kv} onChange={(e) => setKv(e.target.value)} />
      </Field>
      <div className="row">
        <Button tone="primary" disabled={!prompt.trim()} onClick={() =>
          onSubmit({
            system_prompt: prompt.trim(),
            model: model.trim() || undefined,
            config: { tools: tools.split(',').map((s) => s.trim()).filter(Boolean), knowledge_version: kv.trim() || '0' },
          })
        }>
          创建
        </Button>
        <Button onClick={onClose}>取消</Button>
      </div>
    </Modal>
  )
}

function GrayModal({ version, onClose, onSubmit }: { version: number; onClose: () => void; onSubmit: (pct: number) => void }) {
  const [pct, setPct] = useState('10')
  return (
    <Modal title={`灰度 v${version}`} onClose={onClose}>
      <Field label="灰度百分比（0-100）">
        <input type="number" min={0} max={100} value={pct} onChange={(e) => setPct(e.target.value)} />
      </Field>
      <div className="row">
        <Button tone="primary" onClick={() => onSubmit(Math.max(0, Math.min(100, Number(pct) || 0)))}>确认</Button>
        <Button onClick={onClose}>取消</Button>
      </div>
    </Modal>
  )
}

function ContractModal({
  data,
  onClose,
  onEvaluate,
}: {
  data: ContractCheck
  onClose: () => void
  onEvaluate: () => void
}) {
  return (
    <Modal title={`发布契约检查 · v${data.version}`} onClose={onClose}>
      <div className="row" style={{ marginBottom: 14 }}>
        <span>
          总体 <Badge status={data.status} /> {data.blocked ? <b style={{ color: 'var(--red)' }}>（阻断发布）</b> : <span className="muted">（未阻断）</span>}
        </span>
        {data.needs_manual.length > 0 && (
          <span className="small muted">人工签核：{data.needs_manual.join('、')}</span>
        )}
      </div>
      <table className="tbl">
        <thead>
          <tr>
            <th>检查</th>
            <th>结果</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          {data.checks.map((c) => (
            <tr key={c.id}>
              <td className="mono small">{c.id}</td>
              <td>
                <Badge status={c.status} />
              </td>
              <td className="small">{c.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row mt">
        <Button tone="primary" disabled={data.blocked} onClick={onEvaluate}>
          通过回归并发布
        </Button>
        <Button onClick={onClose}>关闭</Button>
      </div>
    </Modal>
  )
}

function RegressionModal({ version, data, onClose }: { version: number; data: Regression; onClose: () => void }) {
  const rate = (data.pass_rate ?? 0) * 100
  const prev = data.previous_pass_rate
  const delta = prev === null || prev === undefined ? null : rate - prev * 100
  const prevTxt = prev === null || prev === undefined ? '无历史基线' : `${(prev * 100).toFixed(0)}%`
  const cases = data.cases ?? []
  return (
    <Modal title={`基准集回归 · v${version}（BADCASES / GOLDEN）`} onClose={onClose}>
      <div className="row mb">
        <span>
          通过率 <b className="mono">{rate.toFixed(0)}%</b>
          <span className="muted small">
            （{data.passed}/{data.total} 通过 · 完成 {data.completed}/{data.total}）
          </span>
        </span>
        <span className="muted small">上一版本 {prevTxt}</span>
        {delta !== null ? (
          <Badge status={data.regressed ? 'fail' : 'pass'}>
            {data.regressed ? `质量回退 ${delta.toFixed(0)}pt` : `对比 ${delta >= 0 ? '+' : ''}${delta.toFixed(0)}pt`}
          </Badge>
        ) : (
          <span className="small muted">（首条回归记录，尚无对比基线）</span>
        )}
      </div>
      {data.regressed && (
        <div className="error-box mb">
          通过率低于上一版本，发布会被回归门禁阻断（RELEASE_REGRESSION_FAILED）。请先修复质量问题；确属误判可到「发布引导」勾选强制发布跳过门禁。
        </div>
      )}
      {cases.length === 0 ? (
        <EmptyState
          title="该版本没有可回归的评测样例"
          desc="先到「效果评测」页录入坏案例 / 黄金集 / 对抗样例，再回来运行回归。"
        />
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>问题</th>
              <th>状态</th>
              <th>判定</th>
              <th>实际工具</th>
              <th>期望工具</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c, i) => (
              <tr key={i}>
                <td className="small">{c.query}</td>
                <td>
                  <Badge status={c.state} />
                </td>
                <td>
                  <Badge status={c.ok ? 'pass' : 'fail'} />
                </td>
                <td className="small mono">{c.tool_calls?.join(' → ') || '—'}</td>
                <td className="small mono">{c.expected_tool_calls?.join(' → ') || '—'}</td>
                <td className="small muted">
                  {c.forbidden_calls && c.forbidden_calls.length > 0 ? `禁调 ${c.forbidden_calls.join(', ')}；` : ''}
                  {c.judge_note || ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="row mt">
        <Button onClick={onClose}>关闭</Button>
      </div>
    </Modal>
  )
}

function CanaryModal({
  version,
  data,
  onClose,
  onHalt,
  onRollback,
}: {
  version: number
  data: CanaryCheck
  onClose: () => void
  onHalt: () => void
  onRollback: () => void
}) {
  const m = data.metrics
  const cell = (label: string, value: React.ReactNode, warn: boolean) => (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value" style={{ color: warn ? 'var(--red)' : undefined, fontSize: 18 }}>{value}</div>
    </div>
  )
  return (
    <Modal title={`Canary 检查 · v${version}`} onClose={onClose}>
      <div className="row" style={{ marginBottom: 12 }}>
        <span>
          结论 <Badge status={data.action === 'stop' ? 'FAILED' : 'PASSED'} />
        </span>
        <span className="small muted">{data.reasons.join(' · ')}</span>
      </div>
      <div className="grid cols-4" style={{ gap: 12 }}>
        {cell('错误率', m.error_rate.toFixed(3), m.error_rate > 0.1)}
        {cell('平均延迟', `${m.avg_latency_s.toFixed(1)}s`, m.avg_latency_s > 30)}
        {cell('工具成功率', m.tool_success_rate === null ? '—' : m.tool_success_rate.toFixed(3), (m.tool_success_rate ?? 1) < 0.9)}
        {cell('RAG recall', m.rag_recall === null ? '—' : m.rag_recall.toFixed(3), (m.rag_recall ?? 1) < 0.3)}
        {cell('LLM 429', m.llm_429_rate.toFixed(3), m.llm_429_rate > 0.2)}
        {cell('负面反馈', m.negative_feedback, m.negative_feedback >= 3)}
        {cell('成本', fmtCost(m.avg_cost), m.avg_cost > 1)}
        {cell('runs', m.runs, false)}
      </div>
      <div className="row mt">
        <Button tone="danger" disabled={data.action !== 'stop'} onClick={onHalt}>停用灰度</Button>
        <Button disabled={data.action !== 'stop'} onClick={onRollback}>回滚</Button>
        <Button onClick={onClose}>关闭</Button>
      </div>
    </Modal>
  )
}
