import { useState } from 'react'
import { useRequest } from 'ahooks'
import { api, ApprovalRow } from '@/api'
import { Badge, Button, Card, ErrorBox, Loading, Modal, TableSkeleton, fmtTime, shortId, stateLabel } from '@/components/ui'
import { useConfirm } from '@/components/Confirm'
import { EmptyState, PageError, PageHeader } from '@/components/Page'

const STATUSES = ['', 'PENDING', 'APPROVED', 'REJECTED', 'TIMEOUT']
const RISK_RANK: Record<string, number> = { CRITICAL: 4, HIGH_RISK_WRITE: 3, LOW_RISK_WRITE: 2, READ: 1 }

export default function Approvals() {
  const { confirm, confirmEl } = useConfirm()
  const { data, loading, error, run } = useRequest((st: string) => api.approvals(st), { defaultParams: [''] as [string] })
  const rows = data?.rows ?? null
  const pendingReq = useRequest(() => api.approvals('PENDING'))
  const pending = pendingReq.data?.rows ?? null
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [busy, setBusy] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [detail, setDetail] = useState<ApprovalRow | null>(null)
  const [detailBusy, setDetailBusy] = useState(false)

  const pendingCount = pending?.length ?? 0
  let maxRisk: string | null = null
  if (pending) for (const a of pending) if (!maxRisk || (RISK_RANK[a.risk_level] ?? 0) > (RISK_RANK[maxRisk] ?? 0)) maxRisk = a.risk_level
  const expiring = (pending ?? []).filter((a) => a.expires_at).length
  const advice =
    pendingCount === 0
      ? '当前没有待审批：不影响线上放行。'
      : maxRisk === 'CRITICAL' || maxRisk === 'HIGH_RISK_WRITE'
        ? `有 ${pendingCount} 条待审批且含${maxRisk === 'CRITICAL' ? '关键操作' : '高风险写'}：建议优先处理，避免阻塞线上调用。`
        : `有 ${pendingCount} 条待审批（风险较低，其中 ${expiring} 条设了到期时间）：建议按时间顺序处理。`


  async function decide(id: string, approve: boolean) {
    setBusy(id)
    setMsg(null)
    try {
      const r: Record<string, unknown> = approve ? await api.approve(id) : await api.reject(id)
      const resumed = (r as { resumed?: { run_id?: string; state?: string } }).resumed
      setMsg(
        resumed && resumed.run_id
          ? { kind: 'ok', text: `${approve ? '已批准' : '已拒绝'} · 被阻塞的 run ${shortId(resumed.run_id)} 已自动续跑（${stateLabel(resumed.state ?? '')}）` }
          : { kind: 'ok', text: approve ? '已批准' : '已拒绝' },
      )
      run(statusFilter)
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy('')
    }
  }

  async function openDetail(id: string) {
    setDetailBusy(true)
    try {
      setDetail(await api.approval(id))
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setDetailBusy(false)
    }
  }

  return (
    <div>
      {confirmEl}
      {error && <div className="mb"><PageError message={(error as Error).message} retry={() => run(statusFilter)} /></div>}
      {msg && <div className="mb">{msg.kind === 'ok' ? <div className="success-box">{msg.text}</div> : <ErrorBox message={msg.text} />}</div>}
      <PageHeader title="审批" desc="高风险工具调用的放行决策与审批门禁" />

      <Card title="审批小结" className="mb">
        {pendingReq.loading ? (
          <TableSkeleton rows={2} cols={3} />
        ) : (
          <>
            <div className="row" style={{ marginBottom: 10 }}>
              <span>待审批 <b>{pendingCount}</b> 条</span>
              {maxRisk && <span className="small muted">· 最高风险 <Badge status={maxRisk} /></span>}
              <span className="small muted">· 设了到期时间 {expiring} 条</span>
            </div>
            <div className="home-hint" style={{ marginBottom: 0 }}>
              <span>🎯 {advice}</span>
            </div>
          </>
        )}
      </Card>

      <Card title={`审批列表（${rows?.length ?? '…'} 条）`}>
        <div className="row mb">
          {STATUSES.map((s) => (
            <button
              key={s}
              className={`btn ${statusFilter === s ? 'primary' : ''}`}
              onClick={() => {
                setStatusFilter(s)
                run(s)
              }}
            >
              {s ? stateLabel(s) : '全部'}
            </button>
          ))}
        </div>
        {loading ? (
          <TableSkeleton rows={5} cols={5} />
        ) : (rows ?? []).length === 0 ? (
          <EmptyState
            title="无审批记录"
            desc="高风险工具调用需要审批时，这里会列出待处理的请求。"
          />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>审批</th>
                <th>时间</th>
                <th>工具</th>
                <th>风险级</th>
                <th>申请人</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((a) => (
                <tr key={a.approval_id}>
                  <td className="mono small">{shortId(a.approval_id)}</td>
                  <td className="mono small muted">{fmtTime(a.created_at)}</td>
                  <td className="mono">{a.tool_ref}</td>
                  <td>
                    <Badge status={a.risk_level} />
                  </td>
                  <td className="small">{a.requester_id}</td>
                  <td>
                    <Badge status={a.status} />
                  </td>
                  <td>
                    <div className="row" style={{ gap: 6 }}>
                      <Button disabled={detailBusy} onClick={() => openDetail(a.approval_id)}>详情</Button>
                      {a.status === 'PENDING' && (
                        <>
                          <Button disabled={busy === a.approval_id} onClick={() => decide(a.approval_id, true)}>
                            批准
                          </Button>
                          <Button tone="danger" disabled={busy === a.approval_id} onClick={() => confirm('拒绝审批', '确定拒绝这条审批吗？', () => decide(a.approval_id, false), { danger: true, confirmText: '拒绝' })}>
                            拒绝
                          </Button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {detail && (
        <Modal title={detailBusy ? '加载中…' : `审批 ${shortId(detail.approval_id)}`} onClose={() => setDetail(null)}>
          {detailBusy ? (
            <Loading />
          ) : (
            <div>
              <div className="row mb" style={{ flexWrap: 'wrap', gap: 8 }}>
                <Badge status={detail.status} />
                <Badge status={detail.risk_level}>{stateLabel(detail.risk_level)}</Badge>
                <span className="mono small">{detail.tool_ref}</span>
              </div>
              <table className="tbl">
                <tbody>
                  <tr><td className="small muted">申请人</td><td className="small mono">{detail.requester_id}</td></tr>
                  <tr><td className="small muted">审批人</td><td className="small mono">{detail.approver_id || '—'}</td></tr>
                  <tr><td className="small muted">创建时间</td><td className="small">{fmtTime(detail.created_at ?? '')}</td></tr>
                  <tr><td className="small muted">过期时间</td><td className="small">{fmtTime(detail.expires_at ?? '')}</td></tr>
                  <tr><td className="small muted">原因 / 备注</td><td className="small">{detail.reason || '—'}</td></tr>
                </tbody>
              </table>
            </div>
          )}
        </Modal>
      )}
    </div>
  )
}
