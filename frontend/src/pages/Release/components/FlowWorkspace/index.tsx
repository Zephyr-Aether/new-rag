import { useCallback, useEffect, useState } from 'react'
import { api, CanaryCheck, ContractCheck, Regression, ReleaseMetrics, Version } from '@/services'
import { Badge, Bar, Button, Card, fmtCost, fmtTime, TableSkeleton } from '@/components'
import { EmptyState, PageError } from '@/components/Page'
import { useConfirm } from '@/components/Confirm'
import { usePermissions } from '@/hooks/usePermissions'
import ReleaseFlow from '../ReleaseFlow'
import GrayModal from '../GrayModal'
import ContractModal from '../ContractModal'
import RegressionModal from '../RegressionModal'
import CanaryModal from '../CanaryModal'
import ReleaseWizard from '../ReleaseWizard'
import VersionDiff from '../VersionDiff'
import { toast } from '@/toast'

const NEXT_ACTION: Record<string, string> = {
  DRAFT: '跑契约+回归 → 发布',
  ACTIVE: '创建新版本 或 灰度',
  GRAY: 'canary 检查 → 升级发布',
  DISABLED: '重新发布',
}

/** 交互式发布流工作区：发布单详情页里"继续当前发布"的核心区域。 */
export default function FlowWorkspace({ agentId }: { agentId: string }) {
  const { confirm, confirmEl } = useConfirm()
  const { can } = usePermissions()
  const [versions, setVersions] = useState<Version[] | null>(null)
  const [metrics, setMetrics] = useState<ReleaseMetrics[] | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')

  // 弹窗
  const [wizardOpen, setWizardOpen] = useState(false)
  const [contractFor, setContractFor] = useState<{ version: number; data: ContractCheck } | null>(null)
  const [regFor, setRegFor] = useState<{ version: number; data: Regression } | null>(null)
  const [grayFor, setGrayFor] = useState<number | null>(null)
  const [canaryFor, setCanaryFor] = useState<{ version: number; data: CanaryCheck } | null>(null)

  const orderedVersions = versions ? [...versions].sort((a, b) => b.version - a.version) : null

  const refresh = useCallback(async () => {
    if (!agentId) return
    const [v, m] = await Promise.all([api.versions(agentId), api.releaseMetrics(agentId)])
    setVersions(v.versions)
    setMetrics(m.metrics)
  }, [agentId])

  useEffect(() => {
    refresh().catch((e: Error) => setErr(e.message))
  }, [refresh])

  async function act(key: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(key)
    setErr('')
    try {
      await fn()
      toast(ok)
      await refresh()
    } catch (e) {
      const message = (e as Error).message
      toast(message, 'err')
    } finally {
      setBusy('')
    }
  }

  async function createVersion(body: { system_prompt: string; model?: string; config?: Record<string, unknown> }) {
    await act('create', () => api.createVersion(agentId, body), '版本已创建')
  }

  async function runContract(v: number) {
    setBusy(`contract-${v}`)
    try {
      const data = await api.contractCheck(agentId, v)
      setContractFor({ version: v, data })
    } catch (e) {
      const message = (e as Error).message
      toast(message, 'err')
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
    } catch (e) {
      const message = (e as Error).message
      toast(message, 'err')
    } finally {
      setBusy('')
    }
  }

  async function runRegression(v: number) {
    setBusy(`reg-${v}`)
    try {
      const data = await api.regression(agentId, v) // §20 基准集回归报告（pass_rate vs 上一版本）
      setRegFor({ version: v, data })
    } catch (e) {
      const message = (e as Error).message
      toast(message, 'err')
    } finally {
      setBusy('')
    }
  }

  async function runCanary(v: number) {
    setBusy(`canary-${v}`)
    try {
      const data = await api.canaryEvaluate(agentId) // §57 对当前 GRAY 版本做 canary 检查
      setCanaryFor({ version: v, data })
    } catch (e) {
      const message = (e as Error).message
      toast(message, 'err')
    } finally {
      setBusy('')
    }
  }

  const refreshRelease = useCallback(() => {
    refresh().catch((e: Error) => setErr(e.message))
  }, [refresh])

  if (!agentId) return null
  return (
    <div className="grid" style={{ gap: 16 }}>
      {confirmEl}
      {err && <PageError message={err} retry={() => refresh().catch((e: Error) => setErr(e.message))} />}

      {orderedVersions !== null && (
        <ReleaseFlow
          agentId={agentId}
          versions={orderedVersions}
          canPublish={can('release:publish')}
          busy={busy}
          contractFor={contractFor}
          regFor={regFor}
          onChanged={refreshRelease}
          onOpenWizard={() => setWizardOpen(true)}
          onCreateVersion={createVersion}
          onRunContract={runContract}
          onRunRegression={runRegression}
          onRunCanary={runCanary}
          onGray={(v) => setGrayFor(v)}
          onPublish={(v) => act(`pub-${v}`, () => api.publish(agentId, v), `v${v} 已全量发布`)}
          onRollback={(v) => confirm('回滚版本', `确定回滚 v${v} 吗？当前版本将停止、流量切到目标版本。`, () => act(`rb-${v}`, () => api.rollback(agentId, v), `已回滚到 v${v}`), { danger: true, confirmText: '回滚' })}
          onHalt={(v) => confirm('停用灰度', `确定停用 v${v} 灰度吗？新流量将回落 ACTIVE 版本。`, () => act(`halt-${v}`, () => api.halt(agentId, v), `v${v} 已停用`), { danger: true, confirmText: '停用灰度' })}
        />
      )}

      {orderedVersions !== null && orderedVersions.length > 0 && (
        <VersionDiff versions={orderedVersions} />
      )}

      <details className="release-details">
        <summary>高级：全部版本与操作</summary>
        <Card title={`版本目录（${orderedVersions?.length ?? '…'}）`} className="mt">
          {orderedVersions === null ? (
            <TableSkeleton rows={5} cols={5} />
          ) : orderedVersions.length === 0 ? (
            <EmptyState
              title="还没有版本"
              desc="到上方「发布流程」创建第一个版本，再进入灰度和放量，Agent 行为变更才有可回退的历史。"
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
      </details>

      <details className="release-details">
        <summary>版本效果数据（详细）</summary>
        <Card title="版本效果" className="mt">
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
      </details>

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
        <ContractModal data={contractFor.data} onClose={() => setContractFor(null)} />
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
