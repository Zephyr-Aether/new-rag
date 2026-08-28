import { useState } from 'react'
import { Button, Modal } from './ui'

export interface ConfirmReq {
  title: string
  desc: string
  confirmText?: string
  danger?: boolean
  onConfirm: () => void
}

/** 危险操作二次确认（基于 shadcn Modal，非 antd） */
export default function Confirm({
  req,
  onClose,
}: {
  req: ConfirmReq | null
  onClose: () => void
}) {
  if (!req) return null
  return (
    <Modal title={req.title} onClose={onClose}>
      <p className="muted" style={{ margin: '0 0 18px', lineHeight: 1.6 }}>{req.desc}</p>
      <div className="row spread">
        <Button onClick={onClose}>取消</Button>
        <Button tone={req.danger ? 'danger' : 'primary'} onClick={() => { req.onConfirm(); onClose() }}>
          {req.confirmText ?? '确认'}
        </Button>
      </div>
    </Modal>
  )
}

/** 页面内使用：const { confirm, confirmEl } = useConfirm()；危险操作调 confirm(title, desc, fn, {danger}) */
export function useConfirm() {
  const [req, setReq] = useState<ConfirmReq | null>(null)
  return {
    confirm: (title: string, desc: string, onConfirm: () => void, opts: { danger?: boolean; confirmText?: string } = {}) =>
      setReq({ title, desc, onConfirm, ...opts }),
    confirmEl: <Confirm req={req} onClose={() => setReq(null)} />,
  }
}
