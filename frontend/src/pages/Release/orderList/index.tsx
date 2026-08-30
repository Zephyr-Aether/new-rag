import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ReleaseOrder } from '@/services'
import { Badge, Button, Card, Loading, fmtTime } from '@/components'
import { EmptyState, FlowChain, PageHeader } from '@/components/Page'
import { useMeta } from '../useMeta'

const ORDER_STATUS: Record<string, { tone: string; label: string }> = {
  open: { tone: 'PROCESSING', label: '进行中' },
  done: { tone: 'OK', label: '已完成' },
  terminated: { tone: 'FAILED', label: '已终止' },
}

/** 发布单列表：查看全部发布单。 */
export default function ReleaseOrderList() {
  const { meta } = useMeta()
  const agentId = meta?.agent_id ?? ''
  const [orders, setOrders] = useState<ReleaseOrder[] | null>(null)

  useEffect(() => {
    if (!agentId) return
    api.releaseOrderList(agentId).then((o) => setOrders(o.orders)).catch(() => setOrders([]))
  }, [agentId])

  if (!meta) return <Loading />

  return (
    <div className="grid" style={{ gap: 16 }}>
      <FlowChain current="release" />
      <PageHeader title="发布单" desc="全部发布单：进行中 / 已完成 / 已终止。" />

      <div className="row" style={{ gap: 10 }}>
        <Button asChild tone="primary"><Link to="/release/orders/new">创建发布单</Link></Button>
        <Button asChild><Link to="/release">返回总览</Link></Button>
      </div>

      <Card title={`发布单（${orders?.length ?? '…'}）`}>
        {orders === null ? (
          <Loading />
        ) : orders.length === 0 ? (
          <EmptyState title="还没有发布单" desc="点击「创建发布单」开始第一轮发布。" />
        ) : (
          <div className="release-order-list">
            {orders.map((o) => {
              const st = ORDER_STATUS[o.status] ?? { tone: 'slate', label: o.status }
              return (
                <div key={o.id} className="release-order-row">
                  <b className="mono">#{o.order_no}</b>
                  <Badge status={st.tone}>{st.label}</Badge>
                  {o.summary && <span className="mono small">{o.summary}</span>}
                  <span className="small muted">{o.created_by || '—'}</span>
                  <span className="small muted">{o.created_at ? fmtTime(o.created_at) : '—'}</span>
                  <span className="spacer" />
                  <Button asChild><Link to={`/release/orders/${o.id}`}>查看</Link></Button>
                </div>
              )
            })}
          </div>
        )}
      </Card>
    </div>
  )
}
