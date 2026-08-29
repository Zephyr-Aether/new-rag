import { Loader2 } from 'lucide-react'

import { cn } from '@/util'

/** 加载指示器（shadcn 风格）：用在按钮 loading、路由加载等。 */
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('h-4 w-4 animate-spin', className)} aria-hidden />
}
