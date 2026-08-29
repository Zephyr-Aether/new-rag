import type { ReactNode } from 'react'

/** 把文本中的查询词高亮（<mark>）。 */
export function highlight(text: string, query: string): ReactNode {
  const terms = query.trim().split(/\s+/).filter(Boolean).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (!terms.length) return <>{text}</>
  const re = new RegExp(`(${terms.join('|')})`, 'gi')
  return text.split(re).map((p, i) =>
    i % 2 === 1 ? (
      <mark key={i} style={{ background: '#fef08a', borderRadius: 2, padding: '0 1px', color: 'inherit' }}>
        {p}
      </mark>
    ) : (
      <span key={i}>{p}</span>
    ),
  )
}
