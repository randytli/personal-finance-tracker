"use client"

import Link from 'next/link'
import { useEffect, useState, type HTMLAttributes, type ReactNode } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, WalletCards } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
  return <details className="group mt-4 border-t pt-3">
    <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-md text-sm font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
      <ChevronRight aria-hidden="true" className="size-4 transition-transform group-open:rotate-90" />View monthly totals
    </summary>
    <ol aria-label="Monthly chart totals" className="mt-3 flex max-h-72 flex-col divide-y overflow-y-auto overscroll-contain rounded-lg border">
      {rows.map(row => <li key={row.month} className="px-3 py-2.5 text-sm">
        <p className="font-medium tabular-nums">{row.month}</p>
        <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
          {columns.map(column => <div key={column.key} className="min-w-0">
            <dt className="text-xs text-muted-foreground">{column.label}</dt>
            <dd className="tabular-nums [overflow-wrap:anywhere]">{money(String(row[column.key]))}</dd>
          </div>)}
        </dl>
      </li>)}
      {rows.length === 0 && <li className="px-3 py-2.5 text-sm text-muted-foreground">No monthly totals in this period.</li>}
    </ol>
  </details>
}

// Inline legend shared by both trend charts; each swatch matches its line stroke.
export function ChartLegend({ items }: { items: Array<{ label: string; color: string; dashed?: boolean }> }) {
  return <ul aria-label="Chart series" className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
    {items.map(item => <li key={item.label} className="inline-flex items-center gap-1.5">
      <span aria-hidden="true" className="inline-block h-0.5 w-3.5 rounded-full"
        style={item.dashed ? { backgroundImage: `linear-gradient(90deg, ${item.color} 60%, transparent 0)`, backgroundSize: '5px 2px' } : { background: item.color }} />
      {item.label}
    </li>)}
  </ul>
}

const NAV_ITEMS = [['/', 'Overview'], ['/review', 'Review'], ['/memberships', 'Memberships']] as const

export function PageNavigation({ current }: { current: 'Overview' | 'Review' | 'Memberships' }) {
  return <header className="sticky top-[env(safe-area-inset-top)] z-20 border-b bg-background/85 backdrop-blur-md supports-[backdrop-filter]:bg-background/70">
    <nav aria-label="Main navigation" className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2 sm:px-6">
      <Link href="/" className="mr-auto inline-flex items-center gap-2 rounded-md text-[15px] font-semibold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span aria-hidden="true" className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm"><WalletCards className="size-4" /></span>
        <span className="max-[379px]:sr-only">PFT</span>
      </Link>
      <div className="flex items-center gap-0.5 rounded-lg bg-muted p-1">
        {NAV_ITEMS.map(([href, label]) =>
          <Button key={href} asChild variant="ghost" size="sm"
            className={cn('px-2.5 text-muted-foreground hover:bg-card/70 sm:px-3', current === label && 'bg-card text-foreground shadow-sm hover:bg-card')}>
            <Link href={href} aria-current={current === label ? 'page' : undefined}>{label}</Link>
          </Button>)}
      </div>
    </nav>
  </header>
}

// Every page shares one content width, gutter and bottom padding (the bulk spacer measures this padding).
export const pageClassName = 'mx-auto max-w-6xl px-4 pb-10 sm:px-6'

export function PageHeader({ title, description, meta, actions }: {
  title: ReactNode; description?: ReactNode; meta?: ReactNode; actions?: ReactNode
}) {
  return <header className="flex flex-col gap-4 pt-6 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between sm:pt-8">
    <div className="min-w-0">
      <h1 className="text-[26px] font-semibold leading-tight sm:text-3xl">{title}</h1>
      {description && <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>}
      {meta}
    </div>
    {actions && <div className="flex flex-wrap items-end gap-3">{actions}</div>}
  </header>
}

// Stacked caption + control. The label text stays the control's accessible name.
export function ControlField({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return <label className={cn('flex min-w-[10rem] flex-1 flex-col gap-1.5 sm:min-w-0 sm:flex-none', className)}>
    <span className="text-xs font-medium text-muted-foreground">{label}</span>
    {children}
  </label>
}

// Shared native control styling keeps selects/month inputs consistent with Button.
export const fieldClassName = 'min-h-9 min-w-0 max-w-full rounded-lg border border-input bg-card px-3 py-1.5 text-sm shadow-sm transition-colors hover:border-ring/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50'

export function SectionCard({ children, className, ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={cn('rounded-xl border bg-card text-card-foreground shadow-[0_1px_2px_rgb(15_23_42/0.04)]', className)} {...props}>{children}</section>
}

export function SectionHeader({ title, description, actions, id, className }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; id?: string; className?: string
}) {
  return <div className={cn('flex flex-wrap items-start justify-between gap-x-4 gap-y-3 px-4 pb-3 pt-4 sm:px-5 sm:pt-5', className)}>
    <div className="min-w-0 flex-1 basis-56">
      <h2 id={id} className="text-base font-semibold leading-6">{title}</h2>
      {description && <div className="mt-0.5 text-sm text-muted-foreground">{description}</div>}
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </div>
}

// Credits (positive amounts) read as inflows; text and sign stay exactly as formatted.
export function Amount({ value, children, className }: { value: string | number; children: ReactNode; className?: string }) {
  return <span className={cn('text-[15px] font-semibold tabular-nums [overflow-wrap:anywhere]', Number(value) > 0 && 'text-success', className)}>{children}</span>
}

export function LoadingState({ label, rows = 3 }: { label: string; rows?: number }) {
  return <div aria-busy="true" className="mt-6 flex flex-col gap-3">
    <span className="sr-only">{label}</span>
    {Array.from({ length: rows }, (_, index) => <div key={index} aria-hidden="true"
      className={cn('animate-pulse rounded-xl bg-muted', index === 0 ? 'h-28' : 'h-16')} />)}
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
  return <details open={open} onToggle={event => setOpen(event.currentTarget.open)} className="group mt-2.5 border-t border-dashed pt-1 md:mt-2 md:border-t-0 md:pt-0">
    <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-2 rounded-md text-xs font-medium text-muted-foreground md:hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
      Details & editing <ChevronDown aria-hidden="true" className="size-4 transition-transform group-open:rotate-180" />
    </summary>
    {/* Explicitly remove closed editor overflow from Safari's scroll geometry. */}
    <div hidden={!open} className="mt-1 min-w-0 md:mt-0">{children}</div>
  </details>
}

export function TransactionTypeBadge({ type, manual }: { type: string | null; manual?: boolean }) {
  return <Badge variant={manual ? 'info' : type ? 'muted' : 'warning'} className="capitalize">
    {type?.replace(/_/g, ' ') || 'unclassified'}{manual !== undefined && ` · ${manual ? 'Manual' : 'Auto'}`}
  </Badge>
}

// Hairline dividers between tiles without gaps or empty grey cells in partial rows.
export const statGridClassName = 'grid overflow-hidden [&>*]:shadow-[1px_0_0_hsl(var(--border)),0_1px_0_hsl(var(--border))]'

export function MetricCard({ label, value, onClick, selected, primary = false }: {
  label: string; value: string; onClick?: () => void; selected?: boolean; primary?: boolean
}) {
  const content = <>
    <span className={cn('block text-[13px] font-medium text-muted-foreground', selected && 'text-primary')}>{label}</span>
    <span className={cn('mt-1 block font-semibold tabular-nums tracking-tight [overflow-wrap:anywhere]', primary ? 'text-2xl lg:text-[28px] lg:leading-9' : 'text-lg')}>{value}</span>
  </>
  const tile = cn('relative block h-full w-full p-4 text-left lg:px-5', primary ? 'sm:py-5' : 'sm:py-4',
    selected && 'bg-accent/60 before:absolute before:inset-x-0 before:top-0 before:h-0.5 before:bg-primary')
  return (
    <div className={cn('h-full min-w-0', value.length > 11 && 'max-sm:col-span-2')}>
      {onClick
        ? <button type="button" onClick={onClick} aria-pressed={selected} className={cn(tile, 'transition-colors hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring')}>{content}</button>
        : <div className={tile}>{content}</div>}
    </div>
  )
}

// Shared ledger row: selection column, then title/amount, a muted meta line, then chips and editors.
export function TransactionRow({ as: Tag = 'div', select, title, amount, meta, children, className }: {
  as?: 'div' | 'article'; select: ReactNode; title: ReactNode; amount: ReactNode; meta?: ReactNode; children?: ReactNode; className?: string
}) {
  return <Tag className={cn('grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 px-4 py-3.5 transition-colors hover:bg-muted/30 sm:px-5', className)}>
    <div data-row-select className="pt-0.5">{select}</div>
    <div className="min-w-0">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4">
        <div className="min-w-0">{title}</div>
        <div className="max-w-[11rem] text-right sm:max-w-none">{amount}</div>
      </div>
      {meta && <div className="mt-0.5 break-words text-[13px] leading-5 text-muted-foreground">{meta}</div>}
      {children}
    </div>
  </Tag>
}

// Inline chip row; editor panels inside it drop to their own full-width line (see editors' order-last).
export function ChipRow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('mt-2 flex flex-wrap items-center gap-1.5', className)}>{children}</div>
}

export function SelectAllBar({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('flex flex-wrap items-center gap-x-4 gap-y-1 border-t bg-muted/50 px-4 py-2 sm:px-5', className)}>{children}</div>
}

export const chartTooltipStyle = {
  borderRadius: 10, borderColor: 'hsl(var(--border))', background: 'hsl(var(--popover))',
  color: 'hsl(var(--popover-foreground))', fontSize: 13, overflowWrap: 'anywhere' as const,
  boxShadow: '0 8px 24px rgb(15 23 42 / 0.08)',
}
