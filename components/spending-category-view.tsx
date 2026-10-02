'use client'

import { Fragment, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { CategoryLabel, categoryColor, categoryMetadata } from '@/components/category-display'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cardClassName } from '@/components/page-presentation'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { cn } from '@/lib/utils'

export type SpendingComponent = 'gross' | 'refunds' | 'reimbursements' | 'card_benefits' | 'net'
export type NetCategory = {
  category: string
  gross_spending: string; refunds: string; reimbursements: string; card_benefits: string; net_spending: string
  expense_transaction_count: number; refund_transaction_count: number; reimbursement_transaction_count: number
  benefit_transaction_count: number; contributing_transaction_count: number
}

// These fields and counts come directly from the accepted M3 monthly payload.
export const netColumns: Array<{
  key: SpendingComponent; label: string; title: string
  field: 'gross_spending' | 'refunds' | 'reimbursements' | 'card_benefits' | 'net_spending'
  count: 'expense_transaction_count' | 'refund_transaction_count' | 'reimbursement_transaction_count' | 'benefit_transaction_count' | 'contributing_transaction_count'
}> = [
  { key: 'gross', label: 'Gross', title: 'Gross Spending', field: 'gross_spending', count: 'expense_transaction_count' },
  { key: 'refunds', label: 'Refunds', title: 'Refunds', field: 'refunds', count: 'refund_transaction_count' },
  { key: 'reimbursements', label: 'Reimbursements', title: 'Reimbursements', field: 'reimbursements', count: 'reimbursement_transaction_count' },
  { key: 'card_benefits', label: 'Card Benefits', title: 'Card Benefits', field: 'card_benefits', count: 'benefit_transaction_count' },
  { key: 'net', label: 'Net', title: 'Net Spending', field: 'net_spending', count: 'contributing_transaction_count' },
]

export default function SpendingCategoryView({ categories, metric, selectedCategory, selectedComponent, onSelect, money, detailsId }: {
  categories: NetCategory[]; metric: SpendingComponent; selectedCategory?: string; selectedComponent?: SpendingComponent
  onSelect: (category: string, component: SpendingComponent) => void
  money: (value: string) => string; detailsId: string
}) {
  const id = useId()
  const [desktop, setDesktop] = useState(false)
  const [breakdownOpen, setBreakdownOpen] = useState(false)
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null)
  useEffect(() => {
    const media = window.matchMedia('(min-width: 768px)')
    setDesktop(media.matches)
    let lastMatch = media.matches
    const update = () => {
      if (media.matches === lastMatch) return
      lastMatch = media.matches
      setDesktop(media.matches)
      setBreakdownOpen(false)
      setExpandedCategory(null)
    }
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  const column = netColumns.find(value => value.key === metric)!
  const sorted = useMemo(() => [...categories].sort((a, b) => Number(b[column.field]) - Number(a[column.field])
    || categoryMetadata(a.category).label.localeCompare(categoryMetadata(b.category).label)), [categories, column])
  const included = sorted.filter(category => category[column.count] > 0)
  const isSelected = (category: string, component: SpendingComponent) => selectedCategory === category && selectedComponent === component
  const selected = (category: string) => isSelected(category, metric)
  const largest = Math.max(0, ...included.map(category => Math.abs(Number(category[column.field]))))
  const share = (category: NetCategory) => largest > 0 ? Math.abs(Number(category[column.field])) / largest * 100 : 0
  const label = (category: string) => categoryMetadata(category).label
  const breakdownId = (category: string) => `${id}-${category}-breakdown`

  function toggle(category: string) { setExpandedCategory(current => current === category ? null : category) }
  function breakdown(category: NetCategory) {
    return <div id={breakdownId(category.category)} role="group" aria-label={`Breakdown for ${label(category.category)}`}>
      <CategoryBreakdownContent category={category} money={money} onSelect={onSelect} isSelected={isSelected} />
    </div>
  }

  return <Sheet open={!desktop && breakdownOpen} onOpenChange={setBreakdownOpen}>
    <section aria-labelledby={`${id}-title`} className="min-w-0">
      <Card className={cardClassName}>
        <CardHeader className="gap-1 px-4 pb-2 pt-4 sm:px-5 sm:pt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle><h2 id={`${id}-title`} className="text-base font-semibold leading-6">{column.title} by Category</h2></CardTitle>
            {!desktop && <SheetTrigger asChild><Button type="button" variant="outline" size="sm">View full breakdown</Button></SheetTrigger>}
          </div>
          <CardDescription className="text-[13px]">Select a category for its transactions, or expand it for the breakdown. Credits use their own posted month and category.</CardDescription>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <CategoryDonut categories={included} field={column.field} title={column.title} money={money}
            isSelected={selected} onSelect={category => onSelect(category, metric)} />
          {desktop ? <table aria-label={`${column.title} by Category`} className="w-full table-fixed text-sm">
            <thead className="text-xs text-muted-foreground"><tr>
              <th scope="col" className="w-[48%] px-4 pb-1.5 pt-2 text-left font-semibold sm:px-5">Category</th>
              <th scope="col" className="w-[30%] px-3 pb-1.5 pt-2 text-right font-semibold">{column.title}</th>
              <th scope="col" className="px-4 pb-1.5 pt-2 text-right font-semibold sm:px-5">Transactions</th>
            </tr></thead>
            <tbody>{included.map(category => <Fragment key={category.category}>
              <tr data-category={category.category} onClick={() => onSelect(category.category, metric)}
                className={cn('cursor-pointer transition-colors hover:bg-accent/70', selected(category.category) && 'bg-primary/15 hover:bg-primary/20')}>
                <td className="py-1 pl-1.5 pr-2 sm:pl-2.5"><div className="flex min-w-0 items-center gap-1">
                  <BreakdownToggle label={label(category.category)} expanded={expandedCategory === category.category}
                    controls={breakdownId(category.category)} onToggle={() => toggle(category.category)} />
                  <span className="flex min-w-0 flex-1 flex-col py-1"><CategoryLabel category={category.category} />
                    <ShareBar category={category.category} percent={share(category)} /></span>
                </div></td>
                <td className="px-3 py-1 text-right"><button type="button" aria-pressed={selected(category.category)}
                  aria-label={`${column.title} transactions for ${label(category.category)}: ${money(category[column.field])}`}
                  className="money whitespace-nowrap rounded-md px-1.5 py-1 font-semibold text-foreground underline-offset-4 hover:text-info hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={event => { event.stopPropagation(); onSelect(category.category, metric) }}>{money(category[column.field])}</button></td>
                <td className="px-4 py-1 text-right tabular-nums text-muted-foreground sm:px-5">{category[column.count]}</td>
              </tr>
              {expandedCategory === category.category && <tr><td colSpan={3} className="px-4 pt-1 sm:px-5">{breakdown(category)}</td></tr>}
            </Fragment>)}</tbody>
          </table> : <div className="px-1.5" aria-label={`${column.title} category list`}>
            {included.map(category => <CategoryRow key={category.category} category={category.category} amount={money(category[column.field])}
              count={category[column.count]} percent={share(category)} selected={selected(category.category)}
              expanded={expandedCategory === category.category} controls={breakdownId(category.category)}
              onToggle={() => toggle(category.category)} onSelect={() => onSelect(category.category, metric)}>
              {breakdown(category)}
            </CategoryRow>)}
          </div>}
          {included.length === 0 && <p className="px-4 pb-3 text-sm text-muted-foreground sm:px-5">No {column.title.toLowerCase()} transactions this month.</p>}
        </CardContent>
      </Card>
    </section>
    {!desktop && <FullCategoryBreakdown categories={categories} money={money} detailsId={detailsId} isSelected={isSelected}
      onSelect={(category, component) => {
        // Selecting opens the transactions below, so the sheet closes; clearing a selection keeps it open.
        if (!isSelected(category, component)) setBreakdownOpen(false)
        onSelect(category, component)
      }} />}
  </Sheet>
}

// Disclosure control for a category's component breakdown. It sits beside, never inside, the
// row's transactions button.
function BreakdownToggle({ label, expanded, controls, onToggle }: {
  label: string; expanded: boolean; controls: string; onToggle: () => void
}) {
  return <button type="button" aria-label={`Breakdown for ${label}`} aria-expanded={expanded} aria-controls={controls}
    className="flex size-10 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    onClick={event => { event.stopPropagation(); onToggle() }}>
    <ChevronDown className={cn('size-4 transition-transform motion-reduce:transition-none', expanded && 'rotate-180')} aria-hidden="true" />
  </button>
}

// Compact category row: [breakdown toggle][transactions button], with the breakdown below.
function CategoryRow({ category, amount, count, percent, selected, expanded, controls, onToggle, onSelect, children }: {
  category: string; amount: string; count: number; percent?: number; selected: boolean; expanded: boolean
  controls: string; onToggle: () => void; onSelect: () => void; children: ReactNode
}) {
  return <div data-category={category}>
    <div className={cn('flex items-center gap-0.5 rounded-xl transition-colors', selected && 'bg-primary/15')}>
      <BreakdownToggle label={categoryMetadata(category).label} expanded={expanded} controls={controls} onToggle={onToggle} />
      <button type="button" aria-pressed={selected} onClick={onSelect}
        className="flex min-h-16 min-w-0 flex-1 items-center justify-between gap-3 rounded-xl py-2.5 pl-1 pr-2.5 text-left hover:bg-accent/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
        <span className="flex min-w-0 flex-1 flex-col gap-1"><CategoryLabel category={category} />
          <span className="pl-[2.375rem] text-xs text-muted-foreground">{count} {count === 1 ? 'transaction' : 'transactions'}</span>
          {percent !== undefined && <ShareBar category={category} percent={percent} />}</span>
        <span className="money shrink-0 whitespace-nowrap text-sm font-semibold">{amount}</span>
      </button>
    </div>
    {expanded && children}
  </div>
}

// Relative size of each category against the largest one, in the category's own colour.
function ShareBar({ category, percent }: { category: string; percent: number }) {
  return <span aria-hidden="true" className="ml-[2.375rem] mt-1 block h-1 overflow-hidden rounded-full bg-muted">
    <span className="block h-full rounded-full" style={{ width: `${Math.max(percent, 1.5)}%`, background: categoryColor(categoryMetadata(category)) }} />
  </span>
}

// Donut of each category's share of the positive total; credits at or below zero are listed but
// not drawn, and small slices keep their true size (the list reaches them). Each segment selects
// its category exactly like the row does.
const TAU = Math.PI * 2
const INNER = 60
const OUTER = 88
const OUTER_SELECTED = 95
// About 2px of surface between segments at the rendered size, never more than a slice can spare.
const GAP = 0.017

function arcPoint(radius: number, angle: number) {
  return `${(100 + radius * Math.sin(angle)).toFixed(3)} ${(100 - radius * Math.cos(angle)).toFixed(3)}`
}

function arcPath(start: number, end: number, outer: number) {
  if (end - start >= TAU - 1e-6) {
    return `M100 ${100 - outer}A${outer} ${outer} 0 1 1 100 ${100 + outer}A${outer} ${outer} 0 1 1 100 ${100 - outer}Z`
      + `M100 ${100 - INNER}A${INNER} ${INNER} 0 1 0 100 ${100 + INNER}A${INNER} ${INNER} 0 1 0 100 ${100 - INNER}Z`
  }
  const large = end - start > Math.PI ? 1 : 0
  return `M${arcPoint(outer, start)}A${outer} ${outer} 0 ${large} 1 ${arcPoint(outer, end)}`
    + `L${arcPoint(INNER, end)}A${INNER} ${INNER} 0 ${large} 0 ${arcPoint(INNER, start)}Z`
}

function sharePercent(share: number) {
  if (share > 0 && share < 0.5) return '<1%'
  if (share < 100 && share > 99.5) return '>99%'
  return `${Math.round(share)}%`
}

function CategoryDonut({ categories, field, title, money, isSelected, onSelect }: {
  categories: NetCategory[]; field: (typeof netColumns)[number]['field']; title: string
  money: (value: string) => string; isSelected: (category: string) => boolean; onSelect: (category: string) => void
}) {
  const [hovered, setHovered] = useState<string | null>(null)
  const [focused, setFocused] = useState<string | null>(null)
  const pointerFocus = useRef(false)
  const positive = categories.map(category => ({ category: category.category, value: Number(category[field]), amount: category[field] }))
    .filter(entry => entry.value > 0)
  const drawnTotal = positive.reduce((sum, entry) => sum + entry.value, 0)
  if (drawnTotal <= 0) return null
  const totalCents = categories.reduce((sum, category) => sum + Math.round(Number(category[field]) * 100), 0)
  const label = (category: string) => categoryMetadata(category).label
  const share = (value: number) => sharePercent(value / drawnTotal * 100)

  let start = 0
  const segments = positive.map(entry => {
    const sweep = entry.value / drawnTotal * TAU
    const pad = positive.length > 1 ? Math.min(GAP, sweep * 0.3) : 0
    const segment = { ...entry, start: start + pad / 2, end: start + sweep - pad / 2, middle: start + sweep / 2 }
    start += sweep
    return segment
  })
  const selectedEntry = categories.find(category => isSelected(category.category))
  const anySelected = selectedEntry !== undefined
  const tipCategory = hovered ?? focused
  const tip = segments.find(segment => segment.category === tipCategory)
  const negativeCount = categories.length - positive.length

  const centreAmount = selectedEntry ? money(selectedEntry[field]) : money((totalCents / 100).toFixed(2))
  // Long amounts step down so they stay on one line inside the ring.
  const amountSize = centreAmount.length <= 9 ? 'text-[9cqw]' : centreAmount.length <= 12 ? 'text-[7.4cqw]' : 'text-[6.2cqw]'
  const selectedValue = selectedEntry ? Number(selectedEntry[field]) : 0

  return <div className="px-4 pb-3 pt-2 sm:px-5">
    <div className="relative mx-auto aspect-square w-full max-w-[18.5rem] [container-type:inline-size] md:max-w-[17rem]">
      <svg viewBox="0 0 200 200" role="group" aria-label={`Share of ${title} by category`} className="block size-full overflow-visible">
        {segments.map(segment => {
          const selected = isSelected(segment.category)
          const color = categoryColor(categoryMetadata(segment.category))
          const name = `${label(segment.category)}, ${share(segment.value)}, ${money(segment.amount)}`
          return <path key={segment.category} d={arcPath(segment.start, segment.end, selected ? OUTER_SELECTED : OUTER)}
            fill={color} fillRule="evenodd" role="button" tabIndex={0} aria-pressed={selected} aria-label={name}
            data-category={segment.category}
            className={cn('cursor-pointer outline-none transition-opacity motion-reduce:transition-none focus-visible:[stroke-width:2.5px] focus-visible:[stroke:hsl(var(--ring))]',
              anySelected && !selected && 'opacity-30', anySelected && !selected && hovered === segment.category && 'opacity-60',
              !anySelected && hovered === segment.category && 'brightness-125')}
            onClick={() => onSelect(segment.category)}
            onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(segment.category) } }}
            onPointerDown={() => { pointerFocus.current = true }}
            onPointerEnter={event => { if (event.pointerType === 'mouse') setHovered(segment.category) }}
            onPointerLeave={() => setHovered(current => current === segment.category ? null : current)}
            onFocus={() => { if (!pointerFocus.current) setFocused(segment.category); pointerFocus.current = false }}
            onBlur={() => setFocused(current => current === segment.category ? null : current)} />
        })}
      </svg>
      <div className="pointer-events-none absolute inset-[24%] flex flex-col items-center justify-center text-center">
        {selectedEntry ? <>
          <p className="line-clamp-2 max-w-full text-[4.6cqw] font-semibold leading-tight">{label(selectedEntry.category)}</p>
          <p className={cn('money mt-0.5 font-bold leading-tight tracking-tight', amountSize)}>{centreAmount}</p>
          <p className="mt-0.5 text-[4.2cqw] font-medium text-muted-foreground">{selectedValue > 0 ? `${share(selectedValue)} of ${title}` : 'Not drawn'}</p>
        </> : <>
          <p className={cn('money font-bold leading-tight tracking-tight', amountSize)}>{centreAmount}</p>
          <p className="mt-0.5 text-[4.6cqw] font-medium text-muted-foreground">All categories</p>
        </>}
      </div>
      {tip && <div role="tooltip" className="pointer-events-none absolute z-10 w-max max-w-[12rem] -translate-x-1/2 -translate-y-[115%] rounded-lg border bg-popover px-2.5 py-1.5 text-left shadow-lg"
        style={{ left: `${(100 + (OUTER + 4) * Math.sin(tip.middle)) / 2}%`, top: `${(100 - (OUTER + 4) * Math.cos(tip.middle)) / 2}%` }}>
        <p className="money text-sm font-bold">{money(tip.amount)}</p>
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span aria-hidden="true" className="h-0.5 w-3 rounded-full" style={{ background: categoryColor(categoryMetadata(tip.category)) }} />
          {label(tip.category)}, {share(tip.value)}
        </p>
      </div>}
    </div>
    {negativeCount > 0 && <p className="mt-2 text-center text-xs text-muted-foreground">{negativeCount} at or below zero not drawn</p>}
  </div>
}

// One accounting disclosure view, independent of the primary metric selection.
function FullCategoryBreakdown({ categories, money, detailsId, isSelected, onSelect }: {
  categories: NetCategory[]; money: (value: string) => string; detailsId: string
  isSelected: (category: string, component: SpendingComponent) => boolean
  onSelect: (category: string, component: SpendingComponent) => void
}) {
  const id = useId()
  const sheetDrilldown = useRef(false)
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null)
  const full = useMemo(() => [...categories].sort((a, b) => Number(b.net_spending) - Number(a.net_spending)
    || categoryMetadata(a.category).label.localeCompare(categoryMetadata(b.category).label)), [categories])
  function selectFromSheet(category: string, component: SpendingComponent) {
    // Only a new selection closes the sheet and moves focus to its transactions.
    sheetDrilldown.current = !isSelected(category, component)
    onSelect(category, component)
  }
  return <SheetContent side="bottom" className="flex h-[92dvh] flex-col rounded-t-xl p-0"
      onCloseAutoFocus={event => {
        if (sheetDrilldown.current) {
          event.preventDefault()
          sheetDrilldown.current = false
          requestAnimationFrame(() => document.getElementById(detailsId)?.focus({ preventScroll: true }))
        }
      }}>
      <SheetHeader className="shrink-0 border-b px-4 py-5 pr-14 text-left">
        <SheetTitle>Full category breakdown</SheetTitle>
        <SheetDescription>Net = Gross − Refunds − Reimbursements − Card Benefits. Select a category for its Net Spending transactions, or expand it for each component.</SheetDescription>
      </SheetHeader>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2.5 pb-[max(1rem,env(safe-area-inset-bottom))] pt-1">
        {full.map(category => <div key={category.category} className="border-b py-1 last:border-b-0">
          <CategoryRow category={category.category} amount={money(category.net_spending)} count={category.contributing_transaction_count}
            selected={isSelected(category.category, 'net')} expanded={expandedCategory === category.category}
            controls={`${id}-${category.category}-breakdown`}
            onToggle={() => setExpandedCategory(current => current === category.category ? null : category.category)}
            onSelect={() => selectFromSheet(category.category, 'net')}>
            <div id={`${id}-${category.category}-breakdown`} role="group" aria-label={`Breakdown for ${categoryMetadata(category.category).label}`}>
              <CategoryBreakdownContent category={category} money={money} onSelect={selectFromSheet} isSelected={isSelected} />
            </div>
          </CategoryRow>
        </div>)}
        {full.length === 0 && <p className="py-4 text-sm text-muted-foreground">No spending contributions this month.</p>}
      </div>
    </SheetContent>
}

// Both inline desktop disclosures and mobile disclosures use the source M3 values. Each component
// row toggles its transactions; selecting the pressed row again clears them.
function CategoryBreakdownContent({ category, money, onSelect, isSelected }: {
  category: NetCategory; money: (value: string) => string
  onSelect: (category: string, component: SpendingComponent) => void
  isSelected: (category: string, component: SpendingComponent) => boolean
}) {
  return <div className="flex flex-col gap-1 pb-4">
            {netColumns.map(value => <button type="button" key={value.key} aria-pressed={isSelected(category.category, value.key)}
              aria-label={`${value.title} transactions for ${categoryMetadata(category.category).label}: ${money(category[value.field])}`}
              className={cn('flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-xl px-3 py-2 text-left text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                isSelected(category.category, value.key) && 'bg-primary/15 hover:bg-primary/20')}
              onClick={() => onSelect(category.category, value.key)}>
              <span className="flex flex-col gap-0.5"><span>{value.label}</span><span className="text-xs text-muted-foreground">{category[value.count]} {category[value.count] === 1 ? 'transaction' : 'transactions'}</span></span>
              <span className="flex items-center gap-2"><span className="money whitespace-nowrap">{money(category[value.field])}</span><ChevronRight className="size-4 text-muted-foreground" aria-hidden="true" /></span>
            </button>)}
          </div>
}
