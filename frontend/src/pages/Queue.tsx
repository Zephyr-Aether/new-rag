import { useState } from 'react'
import { useRequest } from 'ahooks'
import { api } from '../api'
import { Badge, Button, Card, Empty, ErrorBox, Loading, Modal, TableSkeleton, fmtTime, shortId, stateLabel } from '../components/ui'
import { PageHeader } from '../components/Page'
import { useConfirm } from '../components/Confirm'

const STATES = ['', 'QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'DEAD_LETTER', 'CANCELLED', 'EXPIRED']

export default function Queue() {
  const { confirm, confirmEl } = useConfirm()
  const [state, setState] = useState('')
  const { data, loading, error, run } = useRequest((st: string) => api.jobs(st), { defaultParams: [''] as [string] })
  const rows = data?.rows ?? null
  const [err, setErr] = useState('') // 操作（重放/取消/清理）错误
  const [busy, setBusy] = useState('')
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [detailBusy, setDetailBusy] = useState(false)

  const { data: stats, refresh: refreshStats } = useRequest(() => api.queueStats())

  async function openDetail(id: string) {
    setDetailBusy(true)
    try {
      setDetail(await api.queueJob(id))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setDetailBusy(false)
    }
  }

  async function requeue(id: string) {
    setBusy(id)
    try {
      await api.requeue(id)
      run(state)
      refreshStats()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  async function cancel(id: string) {
    setBusy(id)
    try {
      await api.cancelJob(id)
      run(state)
      refreshStats()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  async function expire() {
    setBusy('expire')
    try {
      const r = await api.expireJobs()
      setErr(r.count ? '' : '')
      run(state)
      refreshStats()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  async function sample() {
    setBusy('sample')
    try {
      await api.queueSample()
      refreshStats()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  return (
    <div>
      {confirmEl}
      {(err || error) && <div className="mb"><ErrorBox message={err || (error as Error).message} /></div>}
      <PageHeader title="任务队列" desc="系统异步任务的入队、执行、失败与死信情况" />

      <Card title="状态概览">
        {!stats ? (
          <Loading />
        ) : (
          <div>
            <div className="row" style={{ gap: 12, marginBottom: 14 }}>
              <div className="stat" style={{ flex: 1 }}>
                <div className="label">总任务</div>
                <div className="value">{stats.total}</div>
              </div>
              {Object.entries(stats.by_state).map(([s, n]) => (
                <div className="stat" key={s} style={{ flex: 1 }}>
                  <div className="label">{stateLabel(s)}</div>
                  <div className="value">{n}</div>
                </div>
              ))}
            </div>
            <div className="small muted" style={{ marginBottom: 6 }}>
              {stats.depth && stats.depth.some((d) => d.count > 0) ? '任务队列深度（近 24 小时采样，悬停查看）' : '近 24 小时任务创建量（采样中，悬停查看）'}
            </div>
            <div className="row" style={{ alignItems: 'flex-end', gap: 2, height: 84 }}>
              {(() => {
                const depth = stats.depth && stats.depth.some((d) => d.count > 0) ? stats.depth : stats.trend
                const max = Math.max(1, ...depth.map((t) => t.count))
                return depth.map((t) => {
                  const h = Math.round((t.count / max) * 70)
                  return (
                    <div
                      key={t.hours_ago}
                      title={`${t.hours_ago}小时前：${t.count} 个`}
                      style={{
                        flex: 1, height: `${h}px`, background: 'var(--primary)',
                        borderRadius: '2px 2px 0 0', opacity: t.count ? 1 : 0.15,
                      }}
                    />
                  )
                })
              })()}
            </div>
            <div className="row mt" style={{ justifyContent: 'space-between' }}>
              <span className="small muted">后台定时采样；可手动补一次深度采样</span>
              <Button disabled={busy === 'sample'} onClick={sample}>手动采样</Button>
            </div>
          </div>
        )}
      </Card>

      <div className="mt">
      <Card title="任务队列">
        <div className="row mb">
          {STATES.map((s) => (
            <button
              key={s}
              className={`btn ${state === s ? 'primary' : ''}`}
              onClick={() => {
                setState(s)
                run(s)
              }}
            >
              {s ? stateLabel(s) : '全部'}
            </button>
          ))}
          <button className="btn" disabled={busy === 'expire'} onClick={expire}>
            清理过期任务
          </button>
        </div>
        {loading ? (
          <TableSkeleton rows={5} cols={5} />
        ) : (rows ?? []).length === 0 ? (
          <Empty text="队列空闲：当前没有待处理、排队或执行中的任务" />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Job</th>
                <th>类型</th>
                <th>时间</th>
                <th>状态</th>
                <th>尝试</th>
                <th>错误</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((j) => (
                <tr key={j.job_id}>
                  <td className="mono small">{shortId(j.job_id)}</td>
                  <td className="mono small">{j.job_type}</td>
                  <td className="mono small muted">{fmtTime(j.created_at)}</td>
                  <td>
                    <Badge status={j.state} />
                  </td>
                  <td className="num">{j.attempts}/{j.max_attempts}</td>
                  <td className="small muted">{j.error ? j.error.slice(0, 50) : '—'}</td>
                  <td>
                    <div className="row" style={{ gap: 6 }}>
                      <Button disabled={detailBusy} onClick={() => openDetail(j.job_id)}>详情</Button>
                      {j.state === 'DEAD_LETTER' && (
                        <Button disabled={busy === j.job_id} onClick={() => requeue(j.job_id)}>
                          重放
                        </Button>
                      )}
                      {(j.state === 'CREATED' || j.state === 'QUEUED') && (
  <Button
    disabled={busy === j.job_id}
    onClick={() =>
      confirm('取消任务', '确定取消该任务吗？未执行完成的任务将停止，此操作不可恢复。', () => cancel(j.job_id), { danger: true, confirmText: '取消' })
    }
  >
    取消
  </Button>
)}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      </div>

      {detail && (
        <Modal
          title={detailBusy ? '加载中…' : `任务 ${shortId(String(detail.job_id ?? ''))}`}
          onClose={() => setDetail(null)}
        >
          {detailBusy ? (
            <Loading />
          ) : (
            <div>
              <div className="row mb" style={{ flexWrap: 'wrap', gap: 8 }}>
                <Badge status={String(detail.state ?? '')} />
                <span className="small">类型：{String(detail.job_type ?? '')}</span>
                <span className="small muted">优先级：{String(detail.priority ?? '')}</span>
                <span className="small">尝试：{String(detail.attempts ?? 0)}/{String(detail.max_attempts ?? 0)}</span>
              </div>
              {detail.dedupe_key ? <div className="small muted mb">去重键：{String(detail.dedupe_key)}</div> : null}
              <table className="tbl">
                <tbody>
                  <tr><td className="small muted">创建时间</td><td className="small">{fmtTime(String(detail.created_at ?? ''))}</td></tr>
                  <tr><td className="small muted">开始时间</td><td className="small">{fmtTime(String(detail.started_at ?? ''))}</td></tr>
                  <tr><td className="small muted">完成时间</td><td className="small">{fmtTime(String(detail.finished_at ?? ''))}</td></tr>
                  <tr><td className="small muted">租约至</td><td className="small">{fmtTime(String(detail.lease_until ?? ''))}</td></tr>
                </tbody>
              </table>
              {detail.error ? <div className="mt"><ErrorBox message={String(detail.error)} /></div> : null}
              <div className="small muted mt" style={{ marginBottom: 4 }}>payload</div>
              <pre className="pretty">{JSON.stringify(detail.payload, null, 2)}</pre>
            </div>
          )}
        </Modal>
      )}
    </div>
  )
}
