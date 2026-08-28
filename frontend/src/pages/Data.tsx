import { useState } from 'react'
import { api } from '../api'
import { Button, Card, ErrorBox, Field, SuccessBox } from '../components/ui'
import { PageHeader } from '../components/Page'
import { useConfirm } from '../components/Confirm'

const PRESETS = [
  { label: '更保守', retention: '7', audit: '90', payload: '7' },
  { label: '默认推荐', retention: '30', audit: '180', payload: '30' },
  { label: '更长留存', retention: '90', audit: '365', payload: '90' },
]

export default function Data() {
  const { confirm, confirmEl } = useConfirm()
  const [retention, setRetention] = useState('30')
  const [auditDays, setAuditDays] = useState('180')
  const [payloadDays, setPayloadDays] = useState('30')
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [busy, setBusy] = useState('')

  async function sweep() {
    setBusy('sweep')
    setMsg(null)
    try {
      const r = await api.dataSweep(Number(retention), Number(auditDays), Number(payloadDays))
      setMsg({
        kind: 'ok',
        text: `清扫完成：删 ${r.deleted_runs} run（run ${r.retention_days}d / 审计 ${r.audit_days}d / payload ${r.payload_days}d）`,
      })
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy('')
    }
  }

  function applyPreset(retentionDays: string, auditLogDays: string, payloadLogDays: string) {
    setRetention(retentionDays)
    setAuditDays(auditLogDays)
    setPayloadDays(payloadLogDays)
    setMsg(null)
  }

  return (
    <div>
      {confirmEl}
      <PageHeader title="数据生命周期" desc="保留期清扫（差异化）与租户数据清除" />

      <div className="home-hint">
        <div className="home-hint-copy">
          <span className="home-hint-kicker">使用提示</span>
          <span>这页是运维收口：先确认保留策略，再执行清扫。建议先用“默认推荐”跑通一次，再按合规要求调整。</span>
        </div>
        <Button onClick={() => applyPreset('30', '180', '30')}>恢复默认推荐</Button>
      </div>

      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="保留期清扫（差异化保留期）">
          <div className="row mb">
            {PRESETS.map((p) => (
              <Button key={p.label} onClick={() => applyPreset(p.retention, p.audit, p.payload)}>{p.label}</Button>
            ))}
          </div>
          <Field label="run 保留天数">
            <input type="number" value={retention} onChange={(e) => setRetention(e.target.value)} />
          </Field>
          <Field label="审计日志保留天数">
            <input type="number" value={auditDays} onChange={(e) => setAuditDays(e.target.value)} />
          </Field>
          <Field label="Trace payload 保留天数">
            <input type="number" value={payloadDays} onChange={(e) => setPayloadDays(e.target.value)} />
          </Field>
          <Button
            tone="primary"
            disabled={busy === 'sweep'}
            onClick={() =>
              confirm('执行数据清扫', '按当前保留期删除超期数据（run / 审计 / trace payload）。删除后不可恢复，确定执行吗？', sweep, { danger: true, confirmText: '执行清扫' })
            }
          >
            {busy === 'sweep' ? '清扫中…' : '执行清扫'}
          </Button>
          {msg && <div className="mt">{msg.kind === 'ok' ? <SuccessBox message={msg.text} /> : <ErrorBox message={msg.text} />}</div>}
        </Card>

        <Card title="建议策略">
          <div className="grid" style={{ gap: 10 }}>
            <div className="small muted">如果你只是想让平台先跑起来，通常可以先保留 run 30 天、审计 180 天、payload 30 天。</div>
            <div className="small muted">如果数据量很大，先缩短 payload 保留期，再评估是否需要缩短 run 历史。</div>
            <div className="small muted">如果涉及合规审计，审计日志往往比 run 更需要长期保留。</div>
          </div>
        </Card>
      </div>
    </div>
  )
}
