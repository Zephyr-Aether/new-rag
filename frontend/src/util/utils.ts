import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** shadcn 组件共用：合并 className。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
