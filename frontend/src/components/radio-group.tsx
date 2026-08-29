import * as React from 'react'
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'

import { cn } from '@/util'

/** 单选组（shadcn 风格，基于 radix RadioGroup，适合问卷式选择）。 */
function RadioGroup({ className, ...props }: React.ComponentProps<typeof RadioGroupPrimitive.Root>) {
  return <RadioGroupPrimitive.Root data-slot="radio-group" className={cn('grid gap-2', className)} {...props} />
}

function RadioGroupItem({
  className,
  children,
  ...props
}: React.ComponentProps<typeof RadioGroupPrimitive.Item>) {
  return (
    <label className={cn('flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-muted/50 data-[state=checked]:border-primary', className)}>
      <RadioGroupPrimitive.Item
        data-slot="radio-group-item"
        className="border-input text-primary focus-visible:ring-ring aspect-square h-4 w-4 shrink-0 rounded-full border shadow transition-shadow focus-visible:outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50"
        {...props}
      >
        <RadioGroupPrimitive.Indicator className="flex items-center justify-center">
          <span className="bg-primary h-2 w-2 rounded-full" />
        </RadioGroupPrimitive.Indicator>
      </RadioGroupPrimitive.Item>
      {children}
    </label>
  )
}

export { RadioGroup, RadioGroupItem }
