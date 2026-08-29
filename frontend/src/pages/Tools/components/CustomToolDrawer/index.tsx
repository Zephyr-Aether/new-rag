import { useState } from 'react'
import { Drawer } from 'antd'
import { Badge, Button, ErrorBox, Field, SuccessBox, stateLabel } from '@/components/ui'
import { EmptyState } from '@/components/Page'
import { CodeEditor } from '@/components/CodeEditor'
import { useConfirm } from '@/components/Confirm'
import { CustomTool } from '@/api'

const RISK_OPTIONS = [
  { value: 'READ', label: '只读（READ）' },
  { value: 'LOW_RISK_WRITE', label: '低风险写（LOW_RISK_WRITE）' },
  { value: 'HIGH_RISK_WRITE', label: '高风险写·需审批（HIGH_RISK_WRITE）' },
  { value: 'CRITICAL', label: '关键操作·需审批（CRITICAL）' },
]

const STEPS = ['基础信息', '结构定义', '实现代码']

interface CustomToolDrawerProps {
  open: boolean
  onClose: () => void
  customTools: CustomTool[] | null
  reservedRefs: string[]
  busy: boolean
  msg: { kind: 'ok' | 'err'; text: string } | null
  onSave: (body: { ref: string; description: string; timeout_s: number; risk_level: string; input_schema: Record<string, unknown>; code: string }) => void
  onDelete: (ref: string) => void
}

export default function CustomToolDrawer({ open, onClose, customTools, reservedRefs, busy, msg, onSave, onDelete }: CustomToolDrawerProps) {
  const { confirm, confirmEl } = useConfirm()
  const [step, setStep] = useState(0)
  const [ref, setRef] = useState('')
  const [desc, setDesc] = useState('')
  const [risk, setRisk] = useState('LOW_RISK_WRITE')
  const [timeoutS, setTimeoutS] = useState('5')
  const [schema, setSchema] = useState(`{\n  "type": "object",\n  "properties": {}\n}`)
  const [code, setCode] = useState('def run(args):\n    return {"echo": args}')
  const [dupErr, setDupErr] = useState('')

  function load(t: CustomTool) {
    setStep(0)
    setRef(t.ref)
    setDesc(t.description)
    setRisk(t.risk_level || 'LOW_RISK_WRITE')
    setTimeoutS(String(t.timeout_s))
    setSchema(JSON.stringify(t.input_schema, null, 2))
    setCode(t.code)
    setDupErr('')
  }

  function reset() {
    setStep(0)
    setRef('')
    setDesc('')
    setRisk('LOW_RISK_WRITE')
    setTimeoutS('5')
    setSchema(`{\n  "type": "object",\n  "properties": {}\n}`)
    setCode('def run(args):\n    return {"echo": args}')
    setDupErr('')
  }

  function submit() {
    if (!ref.trim() || !code.trim()) return
    const existing = customTools?.find((t) => t.ref === ref.trim())
    if (!existing && reservedRefs.includes(ref.trim())) {
      setDupErr(`工具 ref「${ref.trim()}」已存在（内置 / MCP / 其他自定义工具），不能重复创建。`)
      return
    }
    setDupErr('')
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(schema || '{}')
    } catch {
      return
    }
    onSave({ ref: ref.trim(), description: desc.trim(), timeout_s: Number(timeoutS) || 5, risk_level: risk, input_schema: parsed, code })
  }

  const canNext = step === 0 ? ref.trim().length > 0 : step === 1 ? (() => { try { JSON.parse(schema) ; return true } catch { return false } })() : code.trim().length > 0

  return (
    <Drawer title="自定义工具" open={open} onClose={onClose} width={640}>
      {confirmEl}
      <div className="custom-steps">
        {STEPS.map((s, i) => (
          <div key={s} className={`custom-step${i === step ? ' on' : ''}${i < step ? ' done' : ''}`}>
            <span className="custom-step-dot">{i < step ? '✓' : i + 1}</span>
            <span>{s}</span>
          </div>
        ))}
      </div>

      {step === 0 && (
        <div className="mt">
          <Field label="工具 ref">
            <input value={ref} onChange={(e) => { setRef(e.target.value); setDupErr('') }} placeholder="my.weather" />
          </Field>
          <Field label="描述">
            <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="这个工具做什么…" />
          </Field>
          <Field label="风险级（高风险写 / 关键操作会触发审批）">
            <select value={risk} onChange={(e) => setRisk(e.target.value)}>
              {RISK_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </Field>
        </div>
      )}
      {step === 1 && (
        <div className="mt">
          <p className="small muted">定义工具的入参结构（input_schema）。保存后试跑区会自动生成表单。</p>
          <CodeEditor value={schema} onChange={setSchema} />
        </div>
      )}
      {step === 2 && (
        <div className="mt">
          <Field label="超时（秒）">
            <input type="number" min={1} max={60} value={timeoutS} onChange={(e) => setTimeoutS(e.target.value)} />
          </Field>
          <Field label="Python 代码（定义 def run(args)，返回 JSON 可序列化；沙箱禁网络 / 限文件访问）">
            <CodeEditor value={code} onChange={setCode} language="python" />
          </Field>
        </div>
      )}

      <div className="row mt" style={{ justifyContent: 'space-between' }}>
        <div className="row" style={{ gap: 8 }}>
          {step > 0 && <Button onClick={() => setStep(step - 1)}>上一步</Button>}
          {step < 2 && <Button tone="primary" disabled={!canNext} onClick={() => setStep(step + 1)}>下一步</Button>}
          {step === 2 && <Button tone="primary" disabled={busy || !canNext} onClick={submit}>{busy ? '保存中…' : '保存工具'}</Button>}
          <Button disabled={busy} onClick={reset}>清空</Button>
        </div>
      </div>
      {dupErr && <div className="mt"><ErrorBox message={dupErr} /></div>}
      {msg && <div className="mt">{msg.kind === 'ok' ? <SuccessBox message={msg.text} /> : <ErrorBox message={msg.text} />}</div>}

      {customTools !== null && customTools.length > 0 && (
        <table className="tbl mt">
          <thead>
            <tr>
              <th>ref</th>
              <th>描述</th>
              <th>风险</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {customTools.map((t) => (
              <tr key={t.ref}>
                <td className="mono small">{t.ref}</td>
                <td className="small muted">{t.description || '—'}</td>
                <td><Badge status={t.risk_level === 'READ' ? 'PASS' : t.risk_level === 'LOW_RISK_WRITE' ? 'WARN' : 'FAIL'}>{stateLabel(t.risk_level)}</Badge></td>
                <td><Badge status={t.registered ? 'PASS' : 'WARN'}>{t.registered ? '已注册' : '未注册'}</Badge></td>
                <td>
                  <div className="row" style={{ gap: 6 }}>
                    <Button disabled={busy} onClick={() => load(t)}>编辑</Button>
                    <Button tone="danger" disabled={busy} onClick={() => confirm('删除自定义工具', `确定删除「${t.ref}」吗？此操作不可撤销。`, () => onDelete(t.ref), { danger: true, confirmText: '删除' })}>删除</Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {customTools !== null && customTools.length === 0 && (
        <div className="mt"><EmptyState title="还没有自定义工具" desc="按上面的三步创建第一个自定义工具，保存后自动热注册。" /></div>
      )}
    </Drawer>
  )
}
