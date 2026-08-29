import { useState } from 'react'
import { Pagination } from '@/components/pagination'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/sheet'
import { useRequest } from 'ahooks'
import { api, EventRow } from '@/services'
import { Badge, Button, Card, ErrorBox, Field, Loading, SuccessBox, TableSkeleton, fmtTime, shortId } from '@/components'
import { EmptyState, PageHeader } from '@/components/Page'
import { toast } from '@/toast'

const PAGE_SIZE = 10
const DEMO_PAYLOAD = { msg: 'hello', from: 'demo', ts: new Date().toISOString() }

export default function Events() {
  const [tab, setTab] = useState<'observe' | 'publish' | 'replay'>('observe')
  const [type, setType] = useState('demo.event')
  const [aggId, setAggId] = useState('agg-1')
  const [key, setKey] = useState('')
  const [payload, setPayload] = useState(JSON.stringify(DEMO_PAYLOAD, null, 2))
  const [busy, setBusy] = useState(false)
  const [replayAgg, setReplayAgg] = useState('')
  const [page, setPage] = useState(1)
  const [replayed, setReplayed] = useState<EventRow[] | null>(null)
  const [replayBefore, setReplayBefore] = useState<{ count: number; by_type: Record<string, number> } | null>(null)
  const [replayErr, setReplayErr] = useState('')
  const [detail, setDetail] = useState<EventRow | null>(null)
  const [fType, setFType] = useState('')
  const [fAgg, setFAgg] = useState('')
  const [fKeyword, setFKeyword] = useState('')
  const { data: rowsData, loading, error, refresh } = useRequest(() => api.events(200))
  const { data: stats, refresh: refreshStats } = useRequest(() => api.eventsStats())

  const rows = rowsData?.rows ?? null
  const trendSeries = stats?.trend ?? []
  const hasTrendSeries = trendSeries.some((t) => t.count > 0)

  const payloadOk = (() => {
    try {
      JSON.parse(payload || '{}')
      return true
    } catch {
      return false
    }
  })()

  const filtered = (rows ?? []).filter((e) => {
    if (fType && e.event_type !== fType) return false
    if (fAgg && !e.aggregate_id.includes(fAgg)) return false
    if (fKeyword && !JSON.stringify(e.payload).toLowerCase().includes(fKeyword.toLowerCase())) return false
    return true
  })

  async function publish() {
    setBusy(true)
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
      toast(r.duplicated ? `幂等命中，返回既有事件 ${shortId(r.event_id)}` : `已发布 ${shortId(r.event_id)}`)
      setTab('observe')
      refresh()
      refreshStats()
    } catch (e) {
      toast((e as Error).message, 'err')
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
      const [before, r] = await Promise.all([
        api.aggregateState(replayAgg.trim()),
        api.replayEvents(replayAgg.trim()),
      ])
      setReplayBefore(before)
      setReplayed(r.events)
    } catch (e) {
      setReplayErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function goReplay(agg: string) {
    setReplayAgg(agg)
    setReplayed(null)
    setReplayBefore(null)
    setReplayErr('')
    setTab('replay')
  }

  function fillExample() {
    setType('demo.event')
    setAggId('agg-1')
    setKey('')
    setPayload(JSON.stringify(DEMO_PAYLOAD, null, 2))
  }

  return (
    <div>
      <PageHeader title="事件" desc="发布、观察、重放三条心智分开；幂等发布、按聚合重放以重建状态。" />

      <div className="event-tabs mb">
        <button type="button" className={`event-tab${tab === 'observe' ? ' on' : ''}`} onClick={() => setTab('observe')}>观察</button>
        <button type="button" className={`event-tab${tab === 'publish' ? ' on' : ''}`} onClick={() => setTab('publish')}>发布</button>
        <button type="button" className={`event-tab${tab === 'replay' ? ' on' : ''}`} onClick={() => setTab('replay')}>重放</button>
      </div>

      {error && <div className="mb"><ErrorBox message={(error as Error).message} /></div>}
      

      {tab === 'observe' && (
        <>
          <Card title="事件概览" className="mb">
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
                  <div className="stat" style={{ flex: 1 }}>
                    <div className="label">按类型</div>
                    <div className="value">{Object.keys(stats.by_type).length} 种</div>
                  </div>
                  <div className="stat" style={{ flex: 1 }}>
                    <div className="label">幂等命中</div>
                    <div className="value">{stats.dedupe_hits ?? 0}</div>
                    <div className="sub">{stats.dedupe_events ?? 0} 条可去重</div>
                  </div>
                  <div className="stat" style={{ flex: 1 }}>
                    <div className="label">重放成功率</div>
                    <div className="value">{stats.replay_total ? `${Math.round(((stats.replay_ok ?? 0) / stats.replay_total) * 100)}%` : '—'}</div>
                    <div className="sub">{stats.replay_ok ?? 0}/{stats.replay_total ?? 0} 次 · {stats.replay_events ?? 0} 条</div>
                  </div>
                </div>
                <div className="small muted" style={{ marginBottom: 6 }}>
                  {hasTrendSeries ? '近 24 小时事件发布量' : '近 24 小时事件发布量（暂无采样数据）'}
                </div>
                <div className="events-chart">
                  {hasTrendSeries ? (
                    <div className="row events-chart-bars" style={{ alignItems: 'flex-end', gap: 2 }}>
                      {trendSeries.map((t) => {
                        const max = Math.max(1, ...trendSeries.map((item) => item.count))
                        const h = Math.round((t.count / max) * 70)
                        return (
                          <div
                            key={t.hours_ago}
                            title={`${t.hours_ago}小时前：${t.count} 条`}
                            style={{ flex: 1, height: `${h}px`, background: 'var(--primary)', borderRadius: '2px 2px 0 0', opacity: t.count ? 1 : 0.15 }}
                          />
                        )
                      })}
                    </div>
                  ) : (
                    <div className="events-chart-empty">
                      <EmptyState title="暂无事件数据" desc="先发布一条事件，这里会展示近 24 小时走势。" />
                    </div>
                  )}
                </div>
              </div>
            )}
          </Card>

          <Card title={`事件流（${filtered.length}${fType || fAgg || fKeyword ? ' 已筛选' : ''}）`}>
            <div className="row mb" style={{ gap: 6, flexWrap: 'wrap' }}>
              <input value={fType} onChange={(e) => { setFType(e.target.value); setPage(1) }} placeholder="按 event_type" style={{ maxWidth: 150 }} />
              <input value={fAgg} onChange={(e) => { setFAgg(e.target.value); setPage(1) }} placeholder="按 aggregate_id" style={{ maxWidth: 150 }} />
              <input value={fKeyword} onChange={(e) => { setFKeyword(e.target.value); setPage(1) }} placeholder="按 payload 关键词" style={{ maxWidth: 170 }} />
            </div>
            {loading ? (
              <TableSkeleton rows={5} cols={5} />
            ) : filtered.length === 0 ? (
              <EmptyState
                title="还没有事件"
                desc="发布第一条事件就能在流里看到；也可以先一键示例发布，再一键重放演示闭环。"
                actions={
                  <div className="empty-state-actions">
                    <Button tone="primary" onClick={() => { fillExample(); setTab('publish') }}>一键示例发布</Button>
                    <Button onClick={() => goReplay('agg-1')}>一键重放演示</Button>
                  </div>
                }
              />
            ) : (
              <>
                <table className="tbl events-table">
                  <thead>
                    <tr>
                      <th>事件</th>
                      <th>类型</th>
                      <th>时间</th>
                      <th>聚合</th>
                      <th>摘要</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((e) => (
                      <tr key={e.event_id} style={{ cursor: 'pointer' }} onClick={() => setDetail(e)}>
                        <td className="mono small">{shortId(e.event_id)}</td>
                        <td><Badge status={e.event_type} /></td>
                        <td className="mono small muted">{fmtTime(e.created_at)}</td>
                        <td className="mono small">
                          <a className="link" onClick={(ev) => { ev.stopPropagation(); goReplay(e.aggregate_id) }}>{shortId(e.aggregate_id)}</a>
                        </td>
                        <td className="small mono events-payload">
                          {JSON.stringify(e.payload).length > 40 ? `${JSON.stringify(e.payload).slice(0, 40)}…` : JSON.stringify(e.payload)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {filtered.length > PAGE_SIZE && (
                  <div className="row mt" style={{ justifyContent: 'flex-end' }}>
                    <Pagination current={page} pageSize={PAGE_SIZE} total={filtered.length} onChange={setPage} />
                  </div>
                )}
              </>
            )}
          </Card>
        </>
      )}

      {tab === 'publish' && (
        <Card title="发布事件">
          <div className="grid cols-2" style={{ gap: 12 }}>
            <Field label="event_type">
              <input value={type} onChange={(e) => setType(e.target.value)} />
            </Field>
            <Field label="聚合标识（重放用它）">
              <input value={aggId} onChange={(e) => setAggId(e.target.value)} />
            </Field>
          </div>
          <Field label="dedupe_key（同键幂等，留空自动生成）">
            <input value={key} onChange={(e) => setKey(e.target.value)} />
          </Field>
          <Field label="payload（JSON）">
            <textarea value={payload} onChange={(e) => setPayload(e.target.value)} style={{ minHeight: 90 }} />
            {!payloadOk && <div className="small" style={{ color: 'var(--danger)', marginTop: 4 }}>JSON 格式有误，无法发布。</div>}
          </Field>
          <div className="row" style={{ gap: 8 }}>
            <Button tone="primary" disabled={busy || !type.trim() || !payloadOk} onClick={publish}>
              {busy ? '发布中…' : '发布'}
            </Button>
            <Button disabled={busy || !payloadOk} onClick={() => setPayload(JSON.stringify(JSON.parse(payload), null, 2))}>格式化</Button>
            <Button onClick={fillExample}>填充示例</Button>
          </div>
          {payloadOk && (
            <details className="event-payload-preview">
              <summary className="small link">折叠预览</summary>
              <pre className="small mono" style={{ marginTop: 8, maxHeight: 160, overflow: 'auto' }}>{JSON.stringify(JSON.parse(payload || '{}'), null, 2)}</pre>
            </details>
          )}
          <div className="small muted mt">发布后自动切到「观察」，可在事件流里看到这条事件。</div>
        </Card>
      )}

      {tab === 'replay' && (
        <Card title="重放事件流">
          <div className="small muted mb">按聚合 ID 重放，按时间序重建该聚合的状态。</div>
          <div className="row">
            <input value={replayAgg} onChange={(e) => setReplayAgg(e.target.value)} placeholder="agg-1" style={{ flex: 1 }} />
            <Button tone="primary" disabled={busy || !replayAgg.trim()} onClick={replay}>
              {busy ? '重放中…' : '重放'}
            </Button>
          </div>
          {replayErr && <div className="mt"><ErrorBox message={replayErr} /></div>}
          {replayed !== null && (
            <div className="mt">
              <SuccessBox message={`重放完成：${replayed.length} 条事件`} />
              {replayBefore && (
                <div className="event-replay-compare">
                  <div className="event-replay-col">
                    <div className="event-replay-col-title">重放前</div>
                    <div className="event-replay-col-value">{replayBefore.count} 条事件</div>
                    <div className="small muted">{Object.entries(replayBefore.by_type).map(([t, n]) => `${t}×${n}`).join('、') || '无'}</div>
                  </div>
                  <div className="event-replay-arrow">→</div>
                  <div className="event-replay-col">
                    <div className="event-replay-col-title">重放后</div>
                    <div className="event-replay-col-value">{replayed.length} 条事件</div>
                    <div className={`small ${replayed.length === replayBefore.count ? 'event-replay-ok' : 'event-replay-diff'}`}>
                      {replayed.length === replayBefore.count ? '状态一致（重放幂等，未改变聚合状态）' : '事件数有变化，请核对'}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="small muted mt">
            也可以在「观察」列表里点某行的聚合 ID，会自动带上这个聚合切到这里。
          </div>
        </Card>
      )}

      {detail && (
        <Sheet open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
      <SheetContent side="right" className="w-[520px] max-w-[520px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{`事件 ${shortId(detail.event_id)}`}</SheetTitle>
        </SheetHeader>
        <div className="px-4">
          <div className="event-detail">
            <div className="memory-preview-line"><b>事件 ID</b> <span className="mono small">{detail.event_id}</span></div>
            <div className="memory-preview-line"><b>类型</b> {detail.event_type}</div>
            <div className="memory-preview-line"><b>聚合</b> <span className="mono small">{detail.aggregate_id}</span> <Button onClick={() => { setDetail(null); goReplay(detail.aggregate_id) }}>去重放</Button></div>
            <div className="memory-preview-line"><b>创建时间</b> {fmtTime(detail.created_at)}</div>
            <div className="event-detail-payload">
              <div className="small muted mb">完整 payload</div>
              <pre className="small mono" style={{ maxHeight: 280, overflow: 'auto' }}>{JSON.stringify(detail.payload, null, 2)}</pre>
              <Button disabled={!detail.payload} onClick={() => navigator.clipboard?.writeText(JSON.stringify(detail.payload, null, 2))}>复制 payload</Button>
            </div>
          </div>
                </div>
      </SheetContent>
    </Sheet>
      )}
    </div>
  )
}
