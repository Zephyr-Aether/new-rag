import { useState } from 'react'
import { Button, Field, Modal } from '@/components/ui'

export default function GrayModal({ version, onClose, onSubmit }: { version: number; onClose: () => void; onSubmit: (pct: number) => void }) {
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
