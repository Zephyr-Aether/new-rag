// 全局操作提示：基于 shadcn 的 sonner Toast（替代自研 pub-sub 渲染）
import { toast as sonnerToast } from 'sonner'

type ToastKind = 'ok' | 'err'

export function toast(text: string, kind: ToastKind = 'ok', ttlMs = 3500): void {
  if (kind === 'err') sonnerToast.error(text, { duration: ttlMs })
  else sonnerToast.success(text, { duration: ttlMs })
}

/** 兼容旧签名（供需要订阅的地方使用；布局不再自渲染，直接由 <Toaster/> 呈现）。 */
export function subscribeToast(_fn: () => void): () => void {
  return () => undefined
}
