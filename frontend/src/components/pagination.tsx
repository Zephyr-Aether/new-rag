import { Button } from '@/components/button'

/** 分页（shadcn 风格，替代 antd Pagination）。total<=pageSize 时返回 null。 */
export function Pagination({
  current,
  pageSize = 10,
  total,
  onChange,
  showSizeChanger: _showSizeChanger = false,
}: {
  current: number
  pageSize?: number
  total: number
  onChange: (page: number) => void
  showSizeChanger?: boolean
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  if (pageCount <= 1) return null

  const pages: number[] = []
  const showAll = pageCount <= 7
  if (showAll) {
    for (let i = 1; i <= pageCount; i++) pages.push(i)
  } else {
    const windowStart = Math.max(1, current - 2)
    const windowEnd = Math.min(pageCount, current + 2)
    if (windowStart > 1) pages.push(1)
    if (windowStart > 2) pages.push(-1) // 省略号
    for (let i = windowStart; i <= windowEnd; i++) pages.push(i)
    if (windowEnd < pageCount - 1) pages.push(-2)
    if (windowEnd < pageCount) pages.push(pageCount)
  }

  return (
    <nav className="flex items-center gap-1" aria-label="分页">
      <Button variant="ghost" size="sm" disabled={current <= 1} onClick={() => onChange(current - 1)}>
        上一页
      </Button>
      {pages.map((p, i) =>
        p < 0 ? (
          <span key={`e${i}`} className="px-1 text-xs text-muted-foreground">
            …
          </span>
        ) : (
          <Button key={p} variant={p === current ? 'default' : 'ghost'} size="sm" onClick={() => onChange(p)}>
            {p}
          </Button>
        ),
      )}
      <Button variant="ghost" size="sm" disabled={current >= pageCount} onClick={() => onChange(current + 1)}>
        下一页
      </Button>
    </nav>
  )
}
