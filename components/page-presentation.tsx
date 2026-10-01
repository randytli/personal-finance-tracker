"use client"

import Link from 'next/link'
import { useEffect, useState, type HTMLAttributes, type ReactNode } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, WalletCards } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
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
  return <nav aria-label="Main navigation" className="sticky top-[env(safe-area-inset-top)] z-20 -mx-4 flex flex-wrap items-center gap-2 border-b bg-background/85 px-4 py-2 backdrop-blur supports-[backdrop-filter]:bg-background/70 sm:-mx-6 sm:gap-4 sm:px-6">
    <Link href="/" className="mr-auto inline-flex items-center gap-2 rounded-md text-base font-semibold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <span aria-hidden="true" className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground"><WalletCards className="size-4" /></span>
      PFT
    </Link>
    <div className="flex items-center gap-1">
      {([['/', 'Overview'], ['/review', 'Review'], ['/memberships', 'Memberships']] as const).map(([href, label]) =>
        <Button key={href} asChild variant="ghost" size="sm"
          className={cn('text-muted-foreground', current === label && 'bg-card text-foreground shadow-sm ring-1 ring-border hover:bg-card')}>
          <Link href={href} aria-current={current === label ? 'page' : undefined}>{label}</Link>
        </Button>)}
    </div>
  </nav>
}

export function PageHeader({ title, description, meta, actions }: {
  title: ReactNode; description?: ReactNode; meta?: ReactNode; actions?: ReactNode
}) {
  return <header className="mt-6 flex flex-wrap items-end justify-between gap-4">
    <div className="min-w-0">
      <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
      {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      {meta}
    </div>
    {actions && <div className="flex w-full flex-wrap items-end gap-3 sm:w-auto">{actions}</div>}
  </header>
}

// Shared native control styling keeps selects/month inputs consistent with Button.
export const fieldClassName = 'min-h-9 min-w-0 max-w-full rounded-md border border-input bg-card px-3 py-1.5 text-sm shadow-sm transition-colors hover:border-ring/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50'

export function SectionCard({ children, className, ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={cn('rounded-xl border bg-card text-card-foreground shadow-sm', className)} {...props}>{children}</section>
}

// Credits (positive amounts) read as inflows; text and sign stay exactly as formatted.
export function Amount({ value, children, className }: { value: string | number; children: ReactNode; className?: string }) {
  return <span className={cn('font-semibold tabular-nums [overflow-wrap:anywhere]', Number(value) > 0 && 'text-success', className)}>{children}</span>
}

export function LoadingState({ label, rows = 3 }: { label: string; rows?: number }) {
  return <div aria-busy="true" className="mt-6 flex flex-col gap-3">
    <span className="sr-only">{label}</span>
    {Array.from({ length: rows }, (_, index) => <div key={index} aria-hidden="true"
      className={cn('animate-pulse rounded-xl border bg-card', index === 0 ? 'h-24' : 'h-16')} />)}
  </div>
}

export function Pagination({ offset, pageSize, total, disabled, onPage, className }: {
  offset: number; pageSize: number; total: number; disabled?: boolean
  onPage: (offset: number) => void; className?: string
}) {
  return <nav aria-label="Pagination" className={cn('flex flex-wrap items-center justify-between gap-3 text-sm', className)}>
    <Button type="button" variant="outline" size="sm" disabled={disabled || offset === 0}
      onClick={() => onPage(Math.max(0, offset - pageSize))}><ChevronLeft aria-hidden="true" />Previous</Button>
    <span className="tabular-nums text-muted-foreground">{total === 0 ? 0 : offset + 1}–{Math.min(offset + pageSize, total)} of {total}</span>
    <Button type="button" variant="outline" size="sm" disabled={disabled || offset + pageSize >= total}
      onClick={() => onPage(offset + pageSize)}>Next<ChevronRight aria-hidden="true" /></Button>
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
  return <details open={open} onToggle={event => setOpen(event.currentTarget.open)} className="group mt-3 border-t pt-3 md:mt-1 md:border-t-0 md:pt-0">
    <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-2 rounded-md text-xs font-medium text-muted-foreground md:hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
      Details & editing <ChevronDown aria-hidden="true" className="size-4 transition-transform group-open:rotate-180" />
    </summary>
    {/* Explicitly remove closed editor overflow from Safari's scroll geometry. */}
    <div hidden={!open} className="mt-2 min-w-0 md:mt-0">{children}</div>
  </details>
}

export function TransactionTypeBadge({ type, manual }: { type: string | null; manual?: boolean }) {
  return <Badge variant={manual ? 'info' : type ? 'muted' : 'warning'} className="capitalize">
    {type?.replace(/_/g, ' ') || 'unclassified'}{manual !== undefined && ` · ${manual ? 'Manual' : 'Auto'}`}
  </Badge>
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

// Shared row geometry: selection column, then content with title/amount and editors aligned.
export function TransactionRow({ as: Tag = 'div', select, title, amount, children, className }: {
  as?: 'div' | 'article'; select: ReactNode; title: ReactNode; amount: ReactNode; children?: ReactNode; className?: string
}) {
  return <Tag className={cn('grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 p-4 sm:px-5', className)}>
    <div className="-mt-0.5">{select}</div>
    <div className="min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <div className="min-w-0 flex-1 basis-40">{title}</div>
        <div className="max-w-full shrink-0 text-right">{amount}</div>
      </div>
      {children}
    </div>
  </Tag>
}

export function SelectAllBar({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('flex flex-wrap items-center gap-x-4 gap-y-1 border-t bg-muted/40 px-4 py-2 sm:px-5', className)}>{children}</div>
}

export const chartTooltipStyle = {
  borderRadius: 8, borderColor: 'hsl(var(--border))', background: 'hsl(var(--popover))',
  color: 'hsl(var(--popover-foreground))', fontSize: 14, overflowWrap: 'anywhere' as const,
  boxShadow: '0 4px 12px rgb(15 23 42 / 0.08)',
}
