// 全局 toast（轻量发布-订阅；Layout 订阅渲染）
type ToastKind = 'ok' | 'err'
export interface ToastItem {
  id: number
  kind: ToastKind
  text: string
}
type Listener = (toasts: ToastItem[]) => void

let toasts: ToastItem[] = []
let listeners = new Set<Listener>()
let seq = 0

function emit() {
  listeners.forEach((l) => l([...toasts]))
}

export function toast(text: string, kind: ToastKind = 'ok', ttlMs = 3500): void {
  const id = ++seq
  toasts = [...toasts, { id, kind, text }]
  emit()
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id)
    emit()
  }, ttlMs)
}

export function subscribeToast(fn: Listener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}
