import { ReactNode } from 'react'
import { useRequest } from 'ahooks'
import { Button } from './ui'

/** 页头：标题 + 副标题 + 右侧主操作（统一所有页面的骨架） */
export function PageHeader({
  title,
  desc,
  actions,
}: {
  title: string
  desc?: string
  actions?: ReactNode
}) {
  return (
    <div className="page-header">
      <div>
        <h2 className="page-title">{title}</h2>
        {desc && <p className="page-desc">{desc}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

/** 统一三态数据 hook：基于 ahooks useRequest（loading/error/data + 手动刷新） */
export function usePageData<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const { data, loading, error, refresh } = useRequest(fetcher, {
    manual: false,
    refreshDeps: deps,
  })
  return { data: (data ?? null) as T | null, loading, error: error ? error.message : '', reload: refresh }
}

/** 统一错误态：带重试 */
export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="error-state">
      <div className="error-state-title">出错了</div>
      <div className="error-state-desc">{message}</div>
      {retry && (
        <Button tone="primary" onClick={retry}>
          重试
        </Button>
      )}
    </div>
  )
}

/** 统一错误态规范：发生了什么 / 影响什么 / 怎么处理 */
export function PageError({ message, retry }: { message?: string; retry?: () => void }) {
  return (
    <div className="error-state">
      <div className="error-state-title">出错了</div>
      <div className="error-state-desc">{message || '请求失败，请稍后重试。'}</div>
      <div className="small muted" style={{ marginBottom: 16 }}>
        影响：当前页面数据未加载，其他功能不受影响。若持续出现，请联系管理员查看系统日志。
      </div>
      {retry && (
        <Button tone="primary" onClick={retry}>
          重试
        </Button>
      )}
    </div>
  )
}

/** 引导式空态：图标 + 说明 + 行动按钮（不再死白一片） */
export function EmptyState({
  title,
  desc,
  action,
  actionLabel,
  actions,
}: {
  title: string
  desc?: string
  action?: () => void
  actionLabel?: string
  actions?: ReactNode
}) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">◇</div>
      <div className="empty-state-body">
        <div className="empty-state-title">{title}</div>
        {desc && <div className="empty-state-desc">{desc}</div>}
        {actions ?? (
          action && actionLabel ? (
            <div className="empty-state-actions">
              <Button tone="primary" onClick={action}>
                {actionLabel}
              </Button>
            </div>
          ) : null
        )}
      </div>
    </div>
  )
}
