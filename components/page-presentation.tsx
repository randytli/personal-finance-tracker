"use client"

import Link from 'next/link'
import { useEffect, useId, useState, type HTMLAttributes, type ReactNode } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, CircleAlert, LayoutGrid, ListChecks, Repeat } from 'lucide-react'
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
  return <details className="group mt-3 border-t pt-3">
    <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-md text-sm font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
      <ChevronRight aria-hidden="true" className="size-4 transition-transform group-open:rotate-90" />View monthly totals
    </summary>
    <ol aria-label="Monthly chart totals" className="mt-3 flex max-h-72 flex-col divide-y overflow-y-auto overscroll-contain rounded-xl border">
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

const NAV_ITEMS = [['/', 'Overview', LayoutGrid], ['/review', 'Review', ListChecks], ['/memberships', 'Memberships', Repeat]] as const

// App mark: a rising line inside a rounded tile.
function AppMark() {
  return <svg aria-hidden="true" viewBox="0 0 24 24" className="size-7 shrink-0">
    <rect width="24" height="24" rx="7" fill="hsl(var(--primary))" />
    <path d="M5.5 15.5 9.5 11l3 2.5 6-6.5" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
}

// Compact pill bar on phones and tablets; a left sidebar from lg up (see .pft-app grid in globals.css).
export function PageNavigation({ current }: { current: 'Overview' | 'Review' | 'Memberships' }) {
  return <header data-app-nav className="sticky top-[env(safe-area-inset-top)] z-20 border-b bg-background/85 backdrop-blur-md lg:static lg:self-stretch lg:border-b-0 lg:border-r lg:bg-card/40 lg:backdrop-blur-none">
    <nav aria-label="Main navigation" className="mx-auto flex max-w-6xl items-center gap-2 px-4 py-2 sm:px-6 lg:sticky lg:top-0 lg:h-dvh lg:flex-col lg:items-stretch lg:gap-7 lg:px-3 lg:py-6">
      <Link href="/" className="mr-auto inline-flex shrink-0 items-center gap-2.5 rounded-full text-[17px] font-bold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:mr-0 lg:px-2">
        <AppMark /><span className="max-[379px]:sr-only">PFT</span>
      </Link>
      <div className="flex min-w-0 items-center gap-0.5 overflow-x-auto rounded-full border bg-card/80 p-1 [scrollbar-width:none] lg:flex-col lg:items-stretch lg:gap-1 lg:overflow-visible lg:rounded-none lg:border-0 lg:bg-transparent lg:p-0">
        {NAV_ITEMS.map(([href, label, Icon]) =>
          <Link key={href} href={href} aria-current={current === label ? 'page' : undefined}
            className={cn('inline-flex shrink-0 items-center justify-center gap-3 rounded-full px-2 py-1.5 text-[13px] font-semibold text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring min-[380px]:px-3 sm:text-sm lg:justify-start lg:rounded-xl lg:py-2.5',
              current === label && 'bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground')}>
            <Icon aria-hidden="true" className="hidden size-[18px] lg:block" />{label}
          </Link>)}
      </div>
    </nav>
  </header>
}

// Every page shares one content width, gutter and bottom padding (the bulk spacer measures this padding).
export const pageClassName = 'mx-auto w-full max-w-6xl px-4 pb-10 sm:px-6 lg:px-8'

export function PageHeader({ title, description, meta, actions }: {
  title: ReactNode; description?: ReactNode; meta?: ReactNode; actions?: ReactNode
}) {
  return <header className="flex flex-col gap-4 pt-6 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between sm:pt-8">
    <div className="min-w-0">
      <h1 className="text-[26px] font-bold leading-tight tracking-tight sm:text-[30px]">{title}</h1>
      {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      {meta}
    </div>
    {actions && <div className="flex flex-wrap items-end gap-3">{actions}</div>}
  </header>
}

// Stacked caption + control. The label text stays the control's accessible name.
export function ControlField({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return <label className={cn('flex min-w-[10rem] flex-1 flex-col gap-1.5 sm:min-w-0 sm:flex-none', className)}>
    <span className="text-xs font-semibold text-muted-foreground">{label}</span>
    {children}
  </label>
}

// Shared native control styling keeps selects/month inputs consistent with Button.
export const fieldClassName = 'min-h-9 min-w-0 max-w-full rounded-xl border border-input bg-muted/60 px-3 py-1.5 text-sm text-foreground transition-colors hover:border-info/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50'

// One card surface: a step lighter than the page, hairline border, large radius, no shadow.
export const cardClassName = 'rounded-[18px] border border-border/80 bg-card text-card-foreground'

export function SectionCard({ children, className, ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={cn(cardClassName, className)} {...props}>{children}</section>
}

// Card header: title on the left, a quiet action or link on the right.
export function SectionHeader({ title, description, actions, id, className }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; id?: string; className?: string
}) {
  return <div className={cn('flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-4 pb-3 pt-4 sm:px-5 sm:pt-5', className)}>
    <div className="min-w-0 flex-1 basis-48">
      <h2 id={id} className="text-base font-semibold leading-6">{title}</h2>
      {description && <div className="mt-0.5 text-[13px] text-muted-foreground">{description}</div>}
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </div>
}

// Quiet "View all ›" style action used in card headers.
export const quietLinkClassName = 'inline-flex items-center gap-0.5 rounded-full px-1 text-sm font-semibold text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-4'

// Small uppercase group label tinted with the info blue (e.g. TODAY, YESTERDAY).
export function GroupLabel({ children, id, className }: { children: ReactNode; id?: string; className?: string }) {
  return <p id={id} className={cn('text-xs font-bold uppercase tracking-[0.08em] text-info', className)}>{children}</p>
}

function parseDay(value: string) {
  const [year, month, day] = value.slice(0, 10).split('-').map(Number)
  return new Date(year, month - 1, day)
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}/

// "Today", "Yesterday", or a weekday date; the year appears only outside the current year.
export function dayLabel(value: string, now = new Date()) {
  if (!DATE_PATTERN.test(value)) return value
  const day = parseDay(value)
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const difference = Math.round((today.getTime() - day.getTime()) / 86_400_000)
  if (difference === 0) return 'Today'
  if (difference === 1) return 'Yesterday'
  return day.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', ...(day.getFullYear() !== today.getFullYear() ? { year: 'numeric' } : {}) })
}

export function shortDay(value: string, now = new Date()) {
  if (!DATE_PATTERN.test(value)) return value
  const day = parseDay(value)
  return day.toLocaleDateString('en-US', { month: 'short', day: 'numeric', ...(day.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}) })
}

// Consecutive rows that share a posted date; server order is preserved.
export function groupByDay<T>(rows: T[], date: (row: T) => string) {
  const groups: Array<{ date: string; rows: T[] }> = []
  for (const row of rows) {
    const value = date(row)
    if (groups.at(-1)?.date === value) groups.at(-1)!.rows.push(row)
    else groups.push({ date: value, rows: [row] })
  }
  return groups
}

export function DayGroup({ date, children }: { date: string; children: ReactNode }) {
  const id = useId()
  return <div role="group" aria-labelledby={id} className="pt-3 first:pt-1">
    <GroupLabel id={id} className="px-2.5 pb-1"><time dateTime={date}>{dayLabel(date)}</time></GroupLabel>
    <div className="flex flex-col">{children}</div>
  </div>
}

// Credits (positive amounts) read as inflows; text and sign stay exactly as formatted.
export function Amount({ value, children, className }: { value: string | number; children: ReactNode; className?: string }) {
  return <span className={cn('money text-[15px] font-semibold', Number(value) > 0 && 'text-success', className)}>{children}</span>
}

// Compact clickable figure for a summary breakdown. The operator is visual only, so the
// accessible name stays "<label> <amount>".
export function StatButton({ label, value, operator, selected, onClick, color }: {
  label: string; value: string; operator?: '−' | '+'; selected?: boolean; onClick: () => void; color?: string
}) {
  return <button type="button" aria-pressed={selected} onClick={onClick}
    className={cn('flex min-w-0 flex-col items-start gap-0.5 rounded-xl px-3 py-2 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
      selected && 'bg-primary/15 ring-1 ring-inset ring-info/60 hover:bg-primary/20')}>
    <span className="flex min-w-0 items-center gap-1.5 text-xs font-semibold text-muted-foreground">
      {color && <span aria-hidden="true" className="size-2 shrink-0 rounded-full" style={{ background: color }} />}{label}
    </span>{' '}
    <span className="money text-sm font-semibold">{operator && <span aria-hidden="true" className="mr-0.5 text-muted-foreground">{operator}</span>}{value}</span>
  </button>
}

export function LoadingState({ label, rows = 3 }: { label: string; rows?: number }) {
  return <div aria-busy="true" className="mt-6 flex flex-col gap-3">
    <span className="sr-only">{label}</span>
    {Array.from({ length: rows }, (_, index) => <div key={index} aria-hidden="true"
      className={cn('animate-pulse rounded-[18px] bg-card', index === 0 ? 'h-40' : 'h-16')} />)}
  </div>
}

export function Pagination({ offset, pageSize, total, disabled, onPage, className }: {
  offset: number; pageSize: number; total: number; disabled?: boolean
  onPage: (offset: number) => void; className?: string
}) {
  return <nav aria-label="Pagination" className={cn('flex flex-wrap items-center justify-between gap-3 text-sm', className)}>
    <Button type="button" variant="outline" size="sm" disabled={disabled || offset === 0}
      onClick={() => onPage(Math.max(0, offset - pageSize))}><ChevronLeft aria-hidden="true" />Previous</Button>
    <span className="money text-muted-foreground">{total === 0 ? 0 : offset + 1}–{Math.min(offset + pageSize, total)} of {total}</span>
    <Button type="button" variant="outline" size="sm" disabled={disabled || offset + pageSize >= total}
      onClick={() => onPage(offset + pageSize)}>Next<ChevronRight aria-hidden="true" /></Button>
  </nav>
}

export function TransactionTools({ children, count }: { children: ReactNode; count?: number }) {
  const [open, setOpen] = useState(true)
  useEffect(() => {
    if (!window.matchMedia) return
    const query = window.matchMedia('(min-width: 768px)')
    setOpen(query.matches)
    const update = () => setOpen(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  return <details open={open} onToggle={event => setOpen(event.currentTarget.open)} className="group mt-1 md:mt-1.5">
    <summary className="inline-flex min-h-9 cursor-pointer list-none items-center gap-2 rounded-full text-xs font-semibold text-muted-foreground md:hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
      <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-foreground">
        {count ? `+${count}` : 'More'}<ChevronDown aria-hidden="true" className="size-3.5 transition-transform group-open:rotate-180" />
      </span>
      Details & editing
    </summary>
    {/* Explicitly remove closed editor overflow from Safari's scroll geometry. */}
    <div hidden={!open} className="mt-1 min-w-0 md:mt-0">{children}</div>
  </details>
}

export function TransactionTypeBadge({ type, manual }: { type: string | null; manual?: boolean }) {
  return <span className={cn('inline-flex max-w-full items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-bold uppercase leading-4 tracking-[0.04em]',
    manual ? 'bg-info/15 text-info' : type ? 'bg-muted text-muted-foreground' : 'bg-warning/15 text-warning')}>
    {!type && <CircleAlert aria-hidden="true" className="size-3 shrink-0" />}
    {type?.replace(/_/g, ' ') || 'unclassified'}{manual !== undefined && ` · ${manual ? 'Manual' : 'Auto'}`}
  </span>
}

// Secondary tags sit behind a "+N" toggle from md up; on phones they are already inside the row's
// collapsed "Details & editing", so they render directly there.
export function MoreTags({ count, children }: { count: number; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  if (count === 0) return null
  return <>
    <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}
      className="hidden h-6 items-center rounded-full bg-muted px-2.5 text-[11px] font-bold text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:inline-flex">
      {open ? 'Less' : `+${count}`}<span className="sr-only"> {open ? 'hide extra details' : 'more details'}</span>
    </button>
    <div id={id} className={cn('contents', !open && 'md:hidden')}>{children}</div>
  </>
}

// Ledger row: name and meta, one primary pill, and a right-aligned amount on a single line from md up.
// On phones the pill drops under the name. Secondary tags and editors follow as children.
export function TransactionRow({ as: Tag = 'div', select, date, title, meta, pill, amount, children, className }: {
  as?: 'div' | 'article'; select: ReactNode; date?: string; title: ReactNode; meta?: ReactNode; pill?: ReactNode
  amount: ReactNode; children?: ReactNode; className?: string
}) {
  return <Tag className={cn('grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-3 rounded-xl px-2.5 py-2.5 transition-colors hover:bg-accent/70 md:grid-cols-[auto_minmax(0,1fr)_auto_auto] md:gap-x-4', className)}>
    <div data-row-select className="col-start-1 row-start-1 pt-0.5">{select}</div>
    <div className="col-start-2 row-start-1 flex min-w-0 gap-3">
      {date && <time dateTime={date} title={date} className="w-12 shrink-0 pt-px text-[13px] font-semibold leading-6 text-muted-foreground">{shortDay(date)}</time>}
      <div className="min-w-0 flex-1">
        {title}
        {meta && <div className="mt-0.5 text-[13px] leading-5 text-muted-foreground [overflow-wrap:anywhere]">{meta}</div>}
      </div>
    </div>
    {pill && <div className="relative col-start-2 col-end-4 row-start-2 mt-2 flex min-w-0 flex-wrap items-center gap-1.5 md:col-start-3 md:col-end-4 md:row-start-1 md:mt-0 md:max-w-[16rem] md:justify-end md:pt-0.5">{pill}</div>}
    <div className="col-start-3 row-start-1 text-right md:col-start-4">{amount}</div>
    {children && <div className="col-start-2 col-end-[-1] row-start-3 min-w-0 md:row-start-2">{children}</div>}
  </Tag>
}

// Inline chip row; editor panels inside it drop to their own full-width line (see editors' order-last).
export function ChipRow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('mt-1.5 flex flex-wrap items-center gap-1.5', className)}>{children}</div>
}

export function SelectAllBar({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-4 py-2 sm:px-5', className)}>{children}</div>
}

export const chartTooltipStyle = {
  borderRadius: 12, borderColor: 'hsl(var(--border))', background: 'hsl(var(--popover))',
  color: 'hsl(var(--popover-foreground))', fontSize: 13, overflowWrap: 'anywhere' as const,
  boxShadow: '0 12px 32px rgb(0 0 0 / 0.45)',
}

export const chartAxisTick = { fontSize: 11, fill: 'hsl(var(--muted-foreground))' }

export type Tracking = { average: number; latest: number; difference: number; flat: boolean; averageOffset: number; tone: 'good' | 'on' | 'bad' }

// Where the latest month sits against the period average. Lower spending is good.
export function trendTracking(values: number[]): Tracking | null {
  const finite = values.filter(Number.isFinite)
  if (finite.length === 0) return null
  const average = finite.reduce((total, value) => total + value, 0) / finite.length
  const max = Math.max(...finite), min = Math.min(...finite)
  const latest = finite[finite.length - 1]
  const difference = latest - average
  const flat = max - min <= Math.max(Math.abs(max), 1) * 1e-6
  // "On average" means within a tenth of the period's own range, so the callout agrees with the line colour.
  const tolerance = Math.max((max - min) * 0.1, 0.005)
  const tone = flat || Math.abs(difference) <= tolerance ? 'on' : difference < 0 ? 'good' : 'bad'
  return { average, latest, difference, flat, averageOffset: flat ? 0.5 : (max - average) / (max - min), tone }
}

export const trackingColor = { good: 'hsl(var(--success))', on: 'hsl(var(--warning))', bad: 'hsl(var(--destructive))' }

export function trackingText(tracking: Tracking) {
  if (tracking.tone === 'on') return '≈ on average'
  return `${tracking.difference < 0 ? '↓' : '↑'} ${compactMoney(Math.abs(tracking.difference))} ${tracking.difference < 0 ? 'under' : 'over'} avg`
}

// Vertical gradient for the tracking line: red above the average, amber at it, green below.
// Called as a function so the chart receives a literal <defs> child (Recharts drops unknown components).
export function trackingGradient(id: string, tracking: Tracking) {
  return <defs>
    <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stopColor={trackingColor.bad} />
      <stop offset={Math.min(1, Math.max(0, tracking.averageOffset))} stopColor={trackingColor.on} />
      <stop offset="1" stopColor={trackingColor.good} />
    </linearGradient>
  </defs>
}

// Decorative inline trend for secondary cards; the values are available in the hero chart's monthly totals.
export function Sparkline({ values, color }: { values: number[]; color: string }) {
  const finite = values.filter(Number.isFinite)
  if (finite.length < 2) return null
  const max = Math.max(...finite), min = Math.min(...finite)
  const points = finite.map((value, index) => `${(index / (finite.length - 1)) * 100},${max === min ? 16 : 28 - ((value - min) / (max - min)) * 24}`).join(' ')
  return <svg aria-hidden="true" viewBox="0 0 100 32" preserveAspectRatio="none" className="mt-3 h-12 w-full overflow-visible">
    <polyline points={points} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
  </svg>
}

// Recharts dot renderer: only the latest point gets a ring and a filled callout chip.
export function trackingCallout(lastIndex: number, tracking: Tracking) {
  const text = trackingText(tracking)
  const color = trackingColor[tracking.tone]
  return function TrackingDot({ cx, cy, index }: { cx?: number; cy?: number; index?: number }) {
    if (index !== lastIndex || cx == null || cy == null) return <g key={`dot-${index}`} />
    const width = text.length * 6.6 + 18
    const x = Math.max(2, cx - width - 10)
    const y = cy < 40 ? cy + 12 : cy - 34
    return <g key="tracking-callout" aria-hidden="true">
      <circle cx={cx} cy={cy} r={6} fill="hsl(var(--card))" stroke={color} strokeWidth={3} />
      <rect x={x} y={y} width={width} height={22} rx={7} fill={color} />
      <text x={x + width / 2} y={y + 15} textAnchor="middle" fontSize={12} fontWeight={700} fill="hsl(var(--background))">{text}</text>
    </g>
  }
}
