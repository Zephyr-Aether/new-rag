import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '@/services'
import type { ReleaseOrderDetail } from '@/services'
import { Badge, Button, Card, Loading, fmtTime } from '@/components'
import { FlowChain, PageError, PageHeader } from '@/components/Page'
import { useConfirm } from '@/components/Confirm'
import { useMeta } from '../useMeta'
import FlowWorkspace from '../components/FlowWorkspace'
import { toast } from '@/toast'

const ORDER_STATUS: Record<string, { tone: string; label: string }> = {
  open: { tone: 'PROCESSING', label: '进行中' },
  done: { tone: 'OK', label: '已完成' },
  terminated: { tone: 'FAILED', label: '已终止' },
}

const NODE_STATUS: Record<string, { tone: string; label: string }> = {
  finish: { tone: 'OK', label: '已完成' },
  process: { tone: 'PROCESSING', label: '进行中' },
  wait: { tone: 'slate', label: '待开始' },
}

/** 发布单详情：看一单的全过程（步骤流转 / 执行结果 / 快照 / 留痕 / 回滚 / 终止 / 重试）。 */
export default function ReleaseOrderDetail() {
  const { orderId } = useParams<{ orderId: string }>()
  const { confirm, confirmEl } = useConfirm()
  const { meta } = useMeta()
  const agentId = meta?.agent_id ?? ''
  const [order, setOrder] = useState<ReleaseOrderDetail | null>(null)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    if (!agentId || !orderId) return
    try {
      setOrder(await api.releaseOrderGet(agentId, orderId))
      setErr('')
    } catch (e) {
      setErr((e as Error).message)
    }
  }, [agentId, orderId])

  useEffect(() => {
    load().catch(() => undefined)
  }, [load])

  if (!meta) return <Loading />
  if (!order) return err ? <PageError message={err} retry={() => load().catch(() => undefined)} /> : <Loading />

  const st = ORDER_STATUS[order.status] ?? { tone: 'slate', label: order.status }
  const isOpen = order.status === 'open'

  const terminate = () =>
    confirm('终止发布', '确定终止当前发布单吗？之后所有步骤只能查看，不能继续操作。', async () => {
      try {
        await api.releaseFlowTerminate(agentId)
        toast('已终止发布')
        await load()
      } catch (e) {
        toast((e as Error).message, 'err')
      }
    }, { danger: true, confirmText: '终止' })

  const rollback = () =>
    confirm('回滚版本', '确定回滚到上一 ACTIVE 版本吗？当前版本将停止、流量切换。', async () => {
      try {
        await api.rollback(agentId)
        toast('已回滚')
      } catch (e) {
        toast((e as Error).message, 'err')
      }
    }, { danger: true, confirmText: '回滚' })

  return (
    <div className="grid" style={{ gap: 16 }}>
      {confirmEl}
      <FlowChain current="release" />
      <PageHeader title={`发布单 #${order.order_no}`} desc="查看这一单的全过程：步骤流转、执行结果、节点快照与留痕。" />

      <Card>
        <div className="row" style={{ gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
          <Badge status={st.tone}>{st.label}</Badge>
          <span className="small muted">创建人 {order.created_by || '—'}</span>
          <span className="small muted">创建 {order.created_at ? fmtTime(order.created_at) : '—'}</span>
          {order.ended_at && <span className="small muted">结束 {fmtTime(order.ended_at)}</span>}
          {order.summary && <span className="mono small">{order.summary}</span>}
        </div>
        <div className="row" style={{ gap: 10 }}>
          <Button asChild><Link to="/release">返回总览</Link></Button>
          <Button asChild><Link to="/release/orders">全部发布单</Link></Button>
          {isOpen && <Button tone="danger" onClick={() => void terminate()}>终止发布</Button>}
          <Button tone="danger" onClick={() => void rollback()}>回滚</Button>
        </div>
      </Card>

      {isOpen ? (
        <FlowWorkspace agentId={agentId} />
      ) : (
        <>
          <Card title="节点快照（关单时）">
            {(order.snapshot?.nodes ?? []).length === 0 ? (
              <p className="small muted">该发布单没有节点快照。</p>
            ) : (
              <div className="release-order-nodes">
                {(order.snapshot.nodes ?? []).map((n) => {
                  const ns = NODE_STATUS[n.status] ?? { tone: 'slate', label: n.status }
                  return (
                    <div key={n.code} className="release-order-node">
                      <div className="release-order-node-head">
                        <span>{n.name}</span>
                        <Badge status={ns.tone}>{ns.label}</Badge>
                      </div>
                      <NodeConfig code={n.code} config={n.config} />
                    </div>
                  )
                })}
              </div>
            )}
          </Card>
          <Card title="执行留痕">
            {order.records.length === 0 ? (
              <p className="small muted">该发布单还没有执行记录。</p>
            ) : (
              <div className="release-history">
                {order.records.map((r, i) => (
                  <div key={i} className={`release-history-item${r.ok ? '' : ' fail'}`}>
                    <div className="release-history-head">
                      <span className={`release-history-verdict${r.ok ? ' ok' : ' bad'}`}>{r.ok ? '✓' : '✗'}</span>
                      <span className="release-history-summary">{r.summary}</span>
                      <span className="small muted">{fmtTime(r.created_at)}</span>
                      <span className="small muted">· {r.operator}</span>
                    </div>
                    {r.detail && <details className="small muted" style={{ marginTop: 6 }}><summary>查看明细</summary>{r.detail}</details>}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  )
}

/** 把节点 config 渲染成可读字段（创建/执行时填的信息），空配置不渲染。 */
function NodeConfig({ code, config }: { code: string; config?: Record<string, unknown> }) {
  const cfg = config ?? {}
  if (code === 'draft') {
    const prompt = String(cfg.system_prompt ?? '')
    const model = String(cfg.model ?? '')
    const tools = String(cfg.tools ?? '')
    const kv = String(cfg.kv ?? '')
    if (!prompt && !model && !tools && !kv) return null
    return (
      <div className="release-node-config">
        {prompt && <div className="release-node-config-prompt">{prompt}</div>}
        <div className="release-node-config-grid">
          <div className="release-node-config-row"><span className="small muted">模型</span><span className="mono small">{model || '默认'}</span></div>
          <div className="release-node-config-row"><span className="small muted">工具集</span><span className="mono small">{tools || '—'}</span></div>
          <div className="release-node-config-row"><span className="small muted">knowledge</span><span className="mono small">{kv || '—'}</span></div>
        </div>
      </div>
    )
  }
  if (code === 'contract') {
    if (cfg.total == null && cfg.passed == null && cfg.failed == null) return null
    return (
      <div className="release-node-config">
        <div className="release-node-config-grid">
          <div className="release-node-config-row"><span className="small muted">总项</span><span className="mono small">{String(cfg.total ?? '—')}</span></div>
          <div className="release-node-config-row"><span className="small muted">通过</span><span className="mono small">{String(cfg.passed ?? '—')}</span></div>
          <div className="release-node-config-row"><span className="small muted">阻断</span><span className="mono small">{String(cfg.failed ?? '—')}</span></div>
        </div>
      </div>
    )
  }
  if (code === 'regression') {
    if (cfg.pass_rate == null && cfg.regressed == null) return null
    const rate = cfg.pass_rate != null ? `${(Number(cfg.pass_rate) * 100).toFixed(0)}%` : '—'
    return (
      <div className="release-node-config">
        <div className="release-node-config-grid">
          <div className="release-node-config-row"><span className="small muted">通过率</span><span className="mono small">{rate}</span></div>
          <div className="release-node-config-row"><span className="small muted">是否退化</span><span className="mono small">{cfg.regressed ? '退化' : '未退化'}</span></div>
        </div>
      </div>
    )
  }
  if (cfg.version != null) {
    return (
      <div className="release-node-config">
        <div className="release-node-config-grid">
          <div className="release-node-config-row"><span className="small muted">涉及版本</span><span className="mono small">v{String(cfg.version)}</span></div>
        </div>
      </div>
    )
  }
  return null
}
