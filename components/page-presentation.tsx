"use client"

import Link from 'next/link'
import { useEffect, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card as SummaryCard, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'

function useMediaQuery(queryString: string) {
  const [narrow, setNarrow] = useState(false)
  useEffect(() => {
    if (!window.matchMedia) return
    const query = window.matchMedia(queryString)
    const update = () => setNarrow(query.matches)
    update()
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [queryString])
  return narrow
}

export function useNarrowViewport() {
  return useMediaQuery('(max-width: 767px)')
}

export function useTransactionPageSize() {
  return useMediaQuery('(max-width: 767px), (pointer: coarse)') ? 10 : 50
}

export function compactMoney(value: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

export function ChartMonthlyTotals({ rows, columns, money }: {
  rows: Array<{ month: string } & Record<string, string | number>>
  columns: Array<{ key: string; label: string }>
  money: (value: string) => string
}) {
  return <details className="mt-4 border-t pt-3">
    <summary className="cursor-pointer rounded-md text-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">View monthly totals</summary>
    <ol aria-label="Monthly chart totals" className="mt-3 flex max-h-72 flex-col gap-3 overflow-y-auto overscroll-contain">
      {rows.map(row => <li key={row.month} className="rounded-md border p-3 text-sm">
        <p className="font-medium">{row.month}</p>
        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
          {columns.map(column => <div key={column.key} className="min-w-0">
            <dt className="text-xs text-muted-foreground">{column.label}</dt>
            <dd className="tabular-nums [overflow-wrap:anywhere]">{money(String(row[column.key]))}</dd>
          </div>)}
        </dl>
      </li>)}
      {rows.length === 0 && <li className="text-sm text-muted-foreground">No monthly totals in this period.</li>}
    </ol>
  </details>
}

export function PageNavigation({ current }: { current: 'Overview' | 'Review' | 'Memberships' }) {
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
    {/* Explicitly remove closed editor overflow from Safari's scroll geometry. */}
    <div hidden={!open} className="mt-2 min-w-0 md:mt-0">{children}</div>
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
      <p className={cn('font-semibold tabular-nums tracking-tight [overflow-wrap:anywhere]', primary ? 'text-2xl sm:text-3xl' : 'text-xl')}>{value}</p>
    </CardContent>
  </>
  return (
    <SummaryCard className={cn('h-full min-w-0 shadow-sm', value.length > 11 && 'col-span-2 lg:col-span-1', selected && 'border-primary ring-2 ring-ring/20')}>
      {onClick
        ? <button type="button" onClick={onClick} aria-pressed={selected} className="h-full w-full rounded-xl text-left transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{content}</button>
        : content}
    </SummaryCard>
  )
}
