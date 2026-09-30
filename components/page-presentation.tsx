"use client"

import Link from 'next/link'
import { useEffect, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card as SummaryCard, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export function PageNavigation({ current }: { current: 'Review' | 'Memberships' }) {
  return <nav aria-label="Main navigation" className="flex flex-wrap items-center gap-2 border-b pb-3 sm:gap-4">
    <Link href="/" className="mr-auto text-base font-semibold tracking-tight">PFT</Link>
    <div className="flex items-center gap-1">
      {([['/', 'Overview'], ['/review', 'Review'], ['/memberships', 'Memberships']] as const).map(([href, label]) =>
        <Button key={href} asChild variant={current === label ? 'secondary' : 'ghost'} size="sm">
          <Link href={href} aria-current={current === label ? 'page' : undefined}>{label}</Link>
        </Button>)}
    </div>
  </nav>
}

export function TransactionTools({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(true)
  useEffect(() => {
    if (!window.matchMedia) return
    const query = window.matchMedia('(min-width: 768px)')
    setOpen(query.matches)
    const update = () => setOpen(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  return <details open={open} onToggle={event => setOpen(event.currentTarget.open)} className="group mt-3 border-t pt-3">
    <summary className="flex min-h-9 cursor-pointer list-none items-center md:hidden justify-between gap-2 rounded-md text-xs font-medium text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
      Details & editing <ChevronDown aria-hidden="true" className="size-4 transition-transform group-open:rotate-180" />
    </summary>
    <div className="mt-2 min-w-0 md:mt-0">{children}</div>
  </details>
}

export function TransactionTypeBadge({ type, manual }: { type: string | null; manual?: boolean }) {
  return <span className={cn('inline-flex max-w-full items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium capitalize',
    manual ? 'border-blue-300 bg-blue-50 text-blue-900' : 'border-slate-300 bg-slate-50 text-slate-800')}>
    {type?.replace(/_/g, ' ') || 'unclassified'}{manual !== undefined && ` · ${manual ? 'Manual' : 'Auto'}`}
  </span>
}

export function MetricCard({ label, value, onClick, selected, primary = false }: {
  label: string; value: string; onClick?: () => void; selected?: boolean; primary?: boolean
}) {
  const content = <>
    <CardHeader className={cn('p-4 pb-1', primary && 'sm:p-5 sm:pb-1')}>
      <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
    </CardHeader>
    <CardContent className={cn('p-4 pt-0', primary && 'sm:p-5 sm:pt-0')}>
      <p className={cn('font-semibold tabular-nums tracking-tight', primary ? 'text-2xl sm:text-3xl' : 'text-xl')}>{value}</p>
    </CardContent>
  </>
  return (
    <SummaryCard className={cn('h-full shadow-sm', selected && 'border-primary ring-2 ring-ring/20')}>
      {onClick
        ? <button type="button" onClick={onClick} aria-pressed={selected} className="h-full w-full rounded-xl text-left transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{content}</button>
        : content}
    </SummaryCard>
  )
}

