import * as React from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'

import { cn } from '@/util'

export interface BreadcrumbItem {
  title: React.ReactNode
  to?: string
}

/** 面包屑（shadcn 风格，替代 antd Breadcrumb）。 */
export function Breadcrumb({ items, className }: { items: BreadcrumbItem[]; className?: string }) {
  return (
    <nav className={cn('flex items-center gap-1 text-sm', className)} aria-label="面包屑">
      {items.map((item, i) => {
        const last = i === items.length - 1
        const node = item.to ? (
          <Link to={item.to} className="text-muted-foreground hover:text-foreground">
            {item.title}
          </Link>
        ) : (
          <span className={last ? 'text-foreground font-medium' : 'text-muted-foreground'}>{item.title}</span>
        )
        return (
          <React.Fragment key={i}>
            {i > 0 && <ChevronRight className="text-muted-foreground h-3.5 w-3.5" />}
            {node}
          </React.Fragment>
        )
      })}
    </nav>
  )
}
