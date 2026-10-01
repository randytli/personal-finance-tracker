"use client"

import Link from 'next/link'
import { useEffect, useState, type HTMLAttributes, type ReactNode } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react'
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

// Wordmark glyph: a ledger sheet closed by the accounting double rule used under statement totals.
function LedgerMark() {
  return <svg aria-hidden="true" viewBox="0 0 20 20" className="size-5 shrink-0">
    <rect x="1" y="1" width="18" height="18" rx="4.5" fill="currentColor" />
    <path d="M5.5 6.5h5M5.5 12h9M5.5 14.5h9" stroke="hsl(var(--background))" strokeWidth="1.3" strokeLinecap="round" />
  </svg>
}

export function PageNavigation({ current }: { current: 'Overview' | 'Review' | 'Memberships' }) {
  return <header className="sticky top-[env(safe-area-inset-top)] z-20 border-b bg-background/90 backdrop-blur-md supports-[backdrop-filter]:bg-background/75">
    <nav aria-label="Main navigation" className="mx-auto flex max-w-6xl items-stretch gap-3 px-4 sm:px-6">
      <Link href="/" className="mr-auto inline-flex items-center gap-2 rounded-md py-3 font-serif text-[19px] font-semibold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <LedgerMark /><span className="max-[379px]:sr-only">PFT</span>
      </Link>
      <div className="flex items-stretch gap-1 sm:gap-3">
        {NAV_ITEMS.map(([href, label]) =>
          <Link key={href} href={href} aria-current={current === label ? 'page' : undefined}
            className={cn('relative inline-flex items-center rounded-md px-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:px-2.5',
              current === label && 'text-foreground after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-foreground')}>
            {label}
          </Link>)}
      </div>
    </nav>
  </header>
}

// Every page shares one content width, gutter and bottom padding (the bulk spacer measures this padding).
export const pageClassName = 'mx-auto max-w-6xl px-4 pb-10 sm:px-6'

export function PageHeader({ title, description, meta, actions }: {
  title: ReactNode; description?: ReactNode; meta?: ReactNode; actions?: ReactNode
}) {
  return <header className="flex flex-col gap-4 pt-7 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between sm:pt-10">
    <div className="min-w-0">
      <h1 className="font-serif text-[30px] font-semibold leading-[1.1] sm:text-[38px]">{title}</h1>
      {description && <p className="mt-2 max-w-prose text-[15px] text-muted-foreground">{description}</p>}
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
export const fieldClassName = 'min-h-9 min-w-0 max-w-full rounded-lg border border-input bg-card px-3 py-1.5 text-sm transition-colors hover:border-foreground/35 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50'

// Sheets hold rows of money; context (charts, actions) sits on the paper under a rule instead.
export const sheetClassName = 'rounded-xl border bg-card text-card-foreground shadow-[0_1px_2px_rgb(23_34_58/0.05),0_6px_20px_-12px_rgb(23_34_58/0.14)]'

export function SectionCard({ children, className, plain = false, ...props }: HTMLAttributes<HTMLElement> & { plain?: boolean }) {
  return <section className={cn(plain ? 'border-t border-foreground/15' : sheetClassName, className)} {...props}>{children}</section>
}

export function SectionHeader({ title, description, actions, id, className, plain = false }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; id?: string; className?: string; plain?: boolean
}) {
  return <div className={cn('flex flex-wrap items-start justify-between gap-x-4 gap-y-3 pb-3', plain ? 'pt-4' : 'px-4 pt-4 sm:px-5 sm:pt-5', className)}>
    <div className="min-w-0 flex-1 basis-56">
      <h2 id={id} className="font-serif text-[19px] font-semibold leading-7">{title}</h2>
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

export type StatementLine = { label: string; value: string; operator?: '−' | '+'; selected?: boolean; onClick?: () => void }

// A reconciliation laid out like a printed statement: signed lines, a rule, then the total over a double rule.
// The operator is visual only, so each line's accessible name stays "<label> <amount>".
export function Statement({ label, lines, total, className }: {
  label: string; lines: StatementLine[]; total: StatementLine; className?: string
}) {
  const row = (line: StatementLine, isTotal: boolean) => {
    const content = <>
      <span aria-hidden="true" className="text-muted-foreground">{isTotal ? '' : line.operator}</span>
      <span className={cn('min-w-0', isTotal ? 'self-center whitespace-nowrap text-sm font-semibold' : 'text-[15px]', line.selected && 'font-semibold')}>{line.label}</span>{' '}
      <span className={cn('justify-self-end text-right [overflow-wrap:anywhere]', isTotal
        ? 'figures border-b-[3px] border-double border-foreground pb-0.5 text-[28px] font-semibold leading-tight min-[400px]:text-[32px] sm:text-[40px]'
        : 'text-[15px] font-medium tabular-nums')}>{line.value}</span>
    </>
    const layout = cn('relative grid w-full grid-cols-[1rem_minmax(0,1fr)_auto] items-baseline gap-x-3 rounded-md px-2 text-left sm:px-3',
      isTotal ? 'py-3' : 'min-h-11 py-2',
      line.selected && 'bg-accent before:absolute before:inset-y-1.5 before:-left-px before:w-0.5 before:rounded-full before:bg-foreground')
    return line.onClick
      ? <button type="button" onClick={line.onClick} aria-pressed={line.selected}
          className={cn(layout, 'transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring')}>{content}</button>
      : <div className={layout}>{content}</div>
  }
  return <section aria-label={label} className={cn('flex min-w-0 flex-col', className)}>
    <ul className="flex flex-col">{lines.map(line => <li key={line.label}>{row(line, false)}</li>)}</ul>
    <div className="mt-1 border-t border-foreground/70" />
    {row(total, true)}
  </section>
}

// Shared ledger row: selection, a date column from md up, then title/amount, a muted meta line, then chips and editors.
export function TransactionRow({ as: Tag = 'div', select, date, title, amount, meta, children, className }: {
  as?: 'div' | 'article'; select: ReactNode; date?: string; title: ReactNode; amount: ReactNode; meta?: ReactNode; children?: ReactNode; className?: string
}) {
  return <Tag className={cn('grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 px-4 py-3.5 transition-colors hover:bg-accent/70 sm:px-5', date && 'md:grid-cols-[auto_6rem_minmax(0,1fr)] md:gap-x-4', className)}>
    <div data-row-select className="pt-0.5">{select}</div>
    {date && <div aria-hidden="true" className="hidden pt-px text-[13px] leading-6 tabular-nums text-muted-foreground md:block">{date}</div>}
    <div className="min-w-0">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4">
        <div className="min-w-0">{title}</div>
        <div className="max-w-[11rem] text-right sm:max-w-none">{amount}</div>
      </div>
      {(meta || date) && <div className="mt-0.5 break-words text-[13px] leading-5 text-muted-foreground">
        {date && <span className="mr-2 tabular-nums md:sr-only">{date}</span>}{meta}
      </div>}
      {children}
    </div>
  </Tag>
}

// Inline chip row; editor panels inside it drop to their own full-width line (see editors' order-last).
export function ChipRow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('mt-2 flex flex-wrap items-center gap-1.5', className)}>{children}</div>
}

export function SelectAllBar({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('flex flex-wrap items-center gap-x-4 gap-y-1 border-t bg-background/60 px-4 py-2 sm:px-5', className)}>{children}</div>
}

export const chartTooltipStyle = {
  borderRadius: 8, borderColor: 'hsl(var(--border))', background: 'hsl(var(--popover))',
  color: 'hsl(var(--popover-foreground))', fontSize: 13, overflowWrap: 'anywhere' as const,
  boxShadow: '0 8px 24px rgb(23 34 58 / 0.10)',
}
