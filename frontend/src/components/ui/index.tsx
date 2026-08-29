import { useState } from 'react'
import type { CSSProperties, ComponentProps, ReactNode } from 'react'
import dayjs from 'dayjs'
import { Eye, EyeOff } from 'lucide-react'
import { Badge as ShadcnBadge } from '@/components/ui/badge'
import { Button as ShadcnButton } from '@/components/ui/button'
import { Card as ShadcnCard, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'

type Tone = 'success' | 'warning' | 'destructive' | 'info' | 'slate'

const STATE_LABELS: Record<string, string> = {
  COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已取消', TIMEOUT: '超时', UNKNOWN: '未知',
  RUNNING: '运行中', PLANNING: '规划中', WAITING_TOOL: '等待工具', OBSERVING: '观察中',
  REFLECTING: '反思中', RETRYING: '重试中', REQUESTED: '已请求', PAUSED: '已暂停',
  WAITING_APPROVAL: '待审批', APPROVAL_REQUIRED: '待审批', APPROVED: '已批准', REJECTED: '已拒绝',
  ACTIVE: '生效中', GRAY: '灰度中', DRAFT: '草稿', DISABLED: '已停用',
  PASSED: '通过', PASS: '通过', READY: '就绪', OK: '正常', ALLOWED: '允许', DENIED: '拒绝',
  QUEUED: '排队中', CREATED: '已创建', SUCCEEDED: '成功', DEAD_LETTER: '死信', EXPIRED: '已过期',
  PENDING: '待处理', NOT_FOUND: '不存在',
  READ: '读取', LOW_RISK_WRITE: '低危写', HIGH_RISK_WRITE: '高危写', CRITICAL: '危险',
  DOWN: '异常', MOCK: '模拟', WARN: '警告', FAIL: '失败', REGRESSION: '回归',
  HEALTHY: '健康', DEGRADED: '降级', UNAVAILABLE: '不可用',
  LOW: '低危', MEDIUM: '中危', HIGH: '高危',
  INACTIVE: '已停用', SKIPPED: '已跳过', MERGED: '已合并', PREPARING: '准备中',
  PROCESSING: '处理中', REQUEUED: '已重回队列', ERROR: '报错', SLEEPING: '休眠',
  CLOSED: '正常', OPEN: '熔断', HALF_OPEN: '试探恢复',
}

export function stateLabel(status: string): string {
  return STATE_LABELS[status.toUpperCase()] ?? status
}

function tone(status: string): Tone {
  const s = status.toUpperCase()
  if (['ACTIVE', 'COMPLETED', 'SUCCEEDED', 'PASSED', 'PASS', 'OK', 'READY', 'ALLOWED', 'CLOSED', 'HEALTHY'].includes(s)) return 'success'
  if (['GRAY', 'RUNNING', 'PENDING', 'WARN', 'QUEUED', 'CREATED', 'PAUSED', 'PROCESSING', 'REQUEUED', 'SLEEPING', 'HALF_OPEN', 'DEGRADED'].includes(s)) return 'warning'
  if (['FAILED', 'DEAD_LETTER', 'REJECTED', 'FAIL', 'DOWN', 'DENIED', 'NOT_FOUND', 'UNKNOWN', 'OPEN', 'ERROR', 'UNAVAILABLE'].includes(s))
    return 'destructive'
  if (['DRAFT'].includes(s)) return 'info'
  return 'slate'
}

export function Badge({ status, children }: { status: string; children?: ReactNode }) {
  return <ShadcnBadge variant={tone(status)}>{children ?? stateLabel(status)}</ShadcnBadge>
}

export function Card({
  title,
  children,
  className = '',
}: {
  title?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <ShadcnCard className={className}>
      {title && (
        <CardHeader className="px-4 pt-3.5 pb-1.5">
          <CardTitle className="text-sm">{title}</CardTitle>
        </CardHeader>
      )}
      <CardContent className="px-4 py-3.5">{children}</CardContent>
    </ShadcnCard>
  )
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <Card className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </Card>
  )
}

export function Button({
  children,
  onClick,
  tone = 'default',
  disabled,
  className = '',
  type,
}: {
  children: ReactNode
  onClick?: () => void
  tone?: 'default' | 'primary' | 'danger'
  disabled?: boolean
  className?: string
  type?: 'button' | 'submit' | 'reset'
}) {
  const variant = tone === 'primary' ? 'default' : tone === 'danger' ? 'destructive' : 'outline'
  return (
    <ShadcnButton variant={variant} size="sm" type={type} onClick={onClick} disabled={disabled} className={className}>
      {children}
    </ShadcnButton>
  )
}

export function Loading() {
  return <div className="loading">加载中…</div>
}

export function PasswordInput({
  wrapperStyle,
  className,
  autoComplete,
  style,
  ...props
}: Omit<ComponentProps<'input'>, 'type'> & {
  wrapperStyle?: CSSProperties
}) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="password-field" style={wrapperStyle}>
      <input
        {...props}
        type={visible ? 'text' : 'password'}
        autoComplete={autoComplete}
        className={className}
        style={{ paddingRight: 36, width: '100%', ...style }}
      />
      <button
        type="button"
        className="password-field-toggle"
        onClick={() => setVisible((v) => !v)}
        title={visible ? '隐藏密码' : '显示密码'}
        aria-label={visible ? '隐藏密码' : '显示密码'}
      >
        {visible ? <EyeOff size={15} /> : <Eye size={15} />}
      </button>
    </div>
  )
}

export function Empty({ text = '暂无数据' }: { text?: string }) {
  return <div className="empty">{text}</div>
}

export function PermissionDenied({ message = '你没有权限访问此页面' }: { message?: string }) {
  return (
    <div style={{ padding: '60px 24px', textAlign: 'center' }}>
      <div style={{ fontSize: 36, marginBottom: 10 }}>🔒</div>
      <div className="small muted">{message}</div>
    </div>
  )
}

export function Skeleton({ height = 16, width = '100%', brand }: { height?: number; width?: string | number; brand?: boolean }) {
  return (
    <div
      className={`agent-skeleton${brand ? ' brand' : ''}`}
      style={{ height, width, borderRadius: 6, animation: 'agent-shimmer 1.4s ease infinite' }}
    />
  )
}

/** 品牌加载动画：跳动品牌圆点 + 平台名。 */
export function BrandLoading({ label = 'Agent Platform' }: { label?: string }) {
  return (
    <div className="brand-loading">
      <span className="brand-dot" />
      <span>{label}</span>
    </div>
  )
}

export function TableSkeleton({ rows = 6, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '12px 0' }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{ display: 'flex', gap: 12 }}>
          {Array.from({ length: cols }).map((_, j) => (
            <Skeleton key={j} height={14} width={`${(j + 1) * 22}%`} />
          ))}
        </div>
      ))}
    </div>
  )
}

/** 站点专属页面骨架：品牌加载动画 + 页头 + 统计卡 + 表格卡，供路由 Suspense fallback 用。 */
export function PageSkeleton({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div>
      <div className="mb" style={{ marginBottom: 14 }}><BrandLoading /></div>
      <div className="page-header">
        <div style={{ flex: 1 }}>
          <Skeleton height={22} width={180} brand />
          <div style={{ marginTop: 8 }}><Skeleton height={13} width={320} brand /></div>
        </div>
        <Skeleton height={34} width={96} brand />
      </div>
      <div className="grid cols-4" style={{ gap: 12 }}>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="card-skeleton">
            <Skeleton height={13} width="42%" brand />
            <div style={{ marginTop: 10 }}><Skeleton height={26} width="60%" brand /></div>
          </div>
        ))}
      </div>
      <div className="mt">
        <div className="card-skeleton">
          <div style={{ marginBottom: 12 }}><Skeleton height={15} width={140} brand /></div>
          <TableSkeleton rows={rows} cols={cols} />
        </div>
      </div>
    </div>
  )
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="error-box">⚠ {message}</div>
}

export function SuccessBox({ message }: { message: string }) {
  return <div className="success-box">✓ {message}</div>
}

export function Field({
  label,
  children,
  className = '',
}: {
  label: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={className ? `field ${className}` : 'field'}>
      <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          {children}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function Bar({ value }: { value: number }) {
  return <Progress value={Math.round(Math.max(0, Math.min(1, value)) * 100)} className="h-1.5 min-w-16" />
}

export function fmtCost(c: unknown): string {
  const n = Number(c ?? 0)
  return n >= 1 ? n.toFixed(3) : n.toFixed(6)
}

export function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 12)}…` : id
}

export function fmtTime(t?: string | null): string {
  if (!t) return '—'
  const d = dayjs(t)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : '—'
}
