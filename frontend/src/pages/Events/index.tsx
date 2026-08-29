import { useState } from 'react'
import { useRequest } from 'ahooks'
import { api, EventRow } from '@/api'
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, SuccessBox, TableSkeleton, fmtTime, shortId } from '@/components/ui'
import { PageHeader } from '@/components/Page'

export default function Events() {
  const [type, setType] = useState('demo.event')
  const [aggId, setAggId] = useState('agg-1')
  const [key, setKey] = useState('')
  const [payload, setPayload] = useState('{"msg":"hi"}')
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [replayAgg, setReplayAgg] = useState('')
  const [replayed, setReplayed] = useState<EventRow[] | null>(null)
  const [replayErr, setReplayErr] = useState('')
  const { data: rowsData, loading, error, refresh } = useRequest(() => api.events(50))
  const { data: stats, refresh: refreshStats } = useRequest(() => api.eventsStats())

  const rows = rowsData?.rows ?? null

  async function publish() {
    setBusy(true)
    setMsg(null)
    try {
      let p: Record<string, unknown> = {}
      try {
        p = payload ? JSON.parse(payload) : {}
      } catch {
        throw new Error('payload 不是合法 JSON')
      }
      const r = await api.publishEvent({
        event_type: type.trim(),
        aggregate_id: aggId.trim() || 'agg-1',
        dedupe_key: key.trim() || crypto.randomUUID(),
        payload: p,
      })
      setMsg({
        kind: 'ok',
        text: r.duplicated ? `幂等命中，返回既有事件 ${shortId(r.event_id)}` : `已发布 ${shortId(r.event_id)}`,
      })
      refresh()
      refreshStats()
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  async function replay() {
    if (!replayAgg.trim()) return
    setBusy(true)
    setReplayErr('')
    setReplayed(null)
    try {
      const r = await api.replayEvents(replayAgg.trim())
      setReplayed(r.events)
    } catch (e) {
      setReplayErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid cols-2" style={{ alignItems: 'start' }}>
      {error && <div style={{ gridColumn: '1 / -1' }}><ErrorBox message={(error as Error).message} /></div>}
      <div style={{ gridColumn: '1 / -1' }}>
        <PageHeader title="事件" desc="系统事件发布与重放：幂等发布、按聚合 ID 重放以重建状态" />
      </div>
      <div style={{ gridColumn: '1 / -1' }}>
      <Card title="事件概览">
        {!stats ? (
          <Loading />
        ) : (
          <div>
            <div className="row" style={{ gap: 12, marginBottom: 14 }}>
              <div className="stat" style={{ flex: 1 }}>
                <div className="label">事件总数</div>
                <div className="value">{stats.total}</div>
              </div>
              {Object.entries(stats.by_type).map(([t, n]) => (
                <div className="stat" key={t} style={{ flex: 1 }}>
                  <div className="label">{t}</div>
                  <div className="value">{n}</div>
                </div>
              ))}
            </div>
            <div className="small muted" style={{ marginBottom: 6 }}>近 24 小时事件发布量（悬停查看）</div>
            <div className="row" style={{ alignItems: 'flex-end', gap: 2, height: 84 }}>
              {(() => {
                const max = Math.max(1, ...stats.trend.map((t) => t.count))
                return stats.trend.map((t) => {
                  const h = Math.round((t.count / max) * 70)
                  return (
                    <div
                      key={t.hours_ago}
                      title={`${t.hours_ago}小时前：${t.count} 条`}
                      style={{
                        flex: 1, height: `${h}px`, background: 'var(--primary)',
                        borderRadius: '2px 2px 0 0', opacity: t.count ? 1 : 0.15,
                      }}
                    />
                  )
                })
              })()}
            </div>
          </div>
        )}
      </Card>
      </div>
      <Card title="发布事件">
        <Field label="event_type">
          <input value={type} onChange={(e) => setType(e.target.value)} />
        </Field>
        <Field label="聚合标识（重放用它）">
          <input value={aggId} onChange={(e) => setAggId(e.target.value)} />
        </Field>
        <Field label="dedupe_key（同键幂等，留空自动生成）">
          <input value={key} onChange={(e) => setKey(e.target.value)} />
        </Field>
        <Field label="payload（JSON）">
          <textarea value={payload} onChange={(e) => setPayload(e.target.value)} style={{ minHeight: 90 }} />
        </Field>
        <Button tone="primary" disabled={busy || !type.trim()} onClick={publish}>
          {busy ? '发布中…' : '发布'}
        </Button>
        {msg && <div className="mt">{msg.kind === 'ok' ? <SuccessBox message={msg.text} /> : <ErrorBox message={msg.text} />}</div>}

        <div className="mt" style={{ borderTop: '1px solid var(--border)', paddingTop: 16 }}>
          <Field label="按聚合 ID 重放事件流">
            <div className="row">
              <input value={replayAgg} onChange={(e) => setReplayAgg(e.target.value)} placeholder="agg-1" />
              <Button disabled={busy || !replayAgg.trim()} onClick={replay}>重放</Button>
            </div>
          </Field>
          {replayErr && <ErrorBox message={replayErr} />}
          {replayed !== null && (
            <p className="small mt">重放得到 {replayed.length} 条事件（按时间序可重建聚合状态）</p>
          )}
        </div>
      </Card>

      <Card title={`事件流（${rows?.length ?? '…'}）`}>
        {loading ? (
          <TableSkeleton rows={5} cols={5} />
        ) : (rows ?? []).length === 0 ? (
          <Empty text="暂无事件" />
        ) : (
          <table className="tbl events-table">
            <thead>
              <tr>
                <th>事件</th>
                <th>类型</th>
                <th>时间</th>
                <th>聚合</th>
                <th>payload</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((e) => (
                <tr key={e.event_id}>
                  <td className="mono small">{shortId(e.event_id)}</td>
                  <td>
                    <Badge status={e.event_type} />
                  </td>
                  <td className="mono small muted">{fmtTime(e.created_at)}</td>
                  <td className="mono small">
                    <a className="link" onClick={() => { setReplayAgg(e.aggregate_id); }}>
                      {shortId(e.aggregate_id)}
                    </a>
                  </td>
                  <td className="small mono events-payload" title={JSON.stringify(e.payload)}>
                    {JSON.stringify(e.payload)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
