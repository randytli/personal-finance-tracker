'use client'

import { Fragment, useEffect, useId, useMemo, useRef, useState } from 'react'
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
  const selected = (category: string) => selectedCategory === category && selectedComponent === metric
  const largest = Math.max(0, ...included.map(category => Math.abs(Number(category[column.field]))))
  const share = (category: NetCategory) => largest > 0 ? Math.abs(Number(category[column.field])) / largest * 100 : 0

  function toggle(category: string) { setExpandedCategory(current => current === category ? null : category) }

  return <Sheet open={!desktop && breakdownOpen} onOpenChange={setBreakdownOpen}>
    <section aria-labelledby={`${id}-title`} className="min-w-0">
      <Card className={cardClassName}>
        <CardHeader className="gap-1 px-4 pb-2 pt-4 sm:px-5 sm:pt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle><h2 id={`${id}-title`} className="text-base font-semibold leading-6">{column.title} by Category</h2></CardTitle>
            {!desktop && <SheetTrigger asChild><Button type="button" variant="outline" size="sm">View full breakdown</Button></SheetTrigger>}
          </div>
          <CardDescription className="text-[13px]">{desktop ? 'Expand a category for its breakdown, or select an amount for transactions.' : 'Select a category for its transactions.'} Credits use their own posted month and category.</CardDescription>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <CategoryDonut categories={included} field={column.field} title={column.title} />
          {desktop ? <table aria-label={`${column.title} by Category`} className="w-full table-fixed text-sm">
            <thead className="text-xs text-muted-foreground"><tr>
              <th scope="col" className="w-[48%] px-4 pb-1.5 pt-2 text-left font-semibold sm:px-5">Category</th>
              <th scope="col" className="w-[30%] px-3 pb-1.5 pt-2 text-right font-semibold">{column.title}</th>
              <th scope="col" className="px-4 pb-1.5 pt-2 text-right font-semibold sm:px-5">Transactions</th>
            </tr></thead>
            <tbody>{included.map(category => <Fragment key={category.category}><tr data-category={category.category} tabIndex={0} aria-selected={selected(category.category)}
              className={cn('cursor-pointer hover:bg-accent/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring', selected(category.category) && 'bg-primary/15')}
              onClick={() => toggle(category.category)}
              onKeyDown={event => { if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); toggle(category.category) } }}>
              <td className="px-4 py-2 sm:px-5"><button type="button" aria-label={`Breakdown for ${categoryMetadata(category.category).label}`}
                aria-expanded={expandedCategory === category.category} aria-controls={`${id}-${category.category}-breakdown`}
                className="flex w-full min-w-0 items-center gap-2 rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={event => { event.stopPropagation(); toggle(category.category) }}>
                <ChevronDown className={cn('size-4 shrink-0 text-muted-foreground', expandedCategory === category.category && 'rotate-180')} aria-hidden="true" />
                <CategoryLabel category={category.category} /></button>
                <ShareBar category={category.category} percent={share(category)} /></td>
              <td className="px-3 py-2.5 text-right"><button type="button"
                aria-label={`${column.title} transactions for ${categoryMetadata(category.category).label}: ${money(category[column.field])}`}
                className="money rounded-md px-1.5 py-1 font-semibold text-foreground underline-offset-4 hover:text-info hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={event => { event.stopPropagation(); onSelect(category.category, metric) }}>{money(category[column.field])}</button></td>
              <td className="px-4 py-2 text-right tabular-nums text-muted-foreground sm:px-5">{category[column.count]}</td>
            </tr>{expandedCategory === category.category && <tr><td colSpan={3} className="px-4 pt-1 sm:px-5">
              <div id={`${id}-${category.category}-breakdown`} role="group" aria-label={`Breakdown for ${categoryMetadata(category.category).label}`}>
                <CategoryBreakdownContent category={category} money={money} onSelect={onSelect} />
              </div>
            </td></tr>}</Fragment>)}</tbody>
          </table> : <div className="px-1.5" aria-label={`${column.title} category list`}>
            {included.map(category => <button type="button" key={category.category} aria-pressed={selected(category.category)}
              className={cn('flex min-h-16 w-full items-center justify-between gap-3 rounded-xl px-2.5 py-2.5 text-left hover:bg-accent/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring', selected(category.category) && 'bg-primary/15')}
              onClick={() => onSelect(category.category, metric)}>
              <span className="flex min-w-0 flex-1 flex-col gap-1"><CategoryLabel category={category.category} />
                <span className="pl-[2.375rem] text-xs text-muted-foreground">{category[column.count]} {category[column.count] === 1 ? 'transaction' : 'transactions'}</span>
                <ShareBar category={category.category} percent={share(category)} /></span>
              <span className="flex shrink-0 items-center gap-1.5"><span className="money text-sm font-semibold">{money(category[column.field])}</span><ChevronRight className="size-4 text-muted-foreground" aria-hidden="true" /></span>
            </button>)}
          </div>}
          {included.length === 0 && <p className="px-4 pb-3 text-sm text-muted-foreground sm:px-5">No {column.title.toLowerCase()} transactions this month.</p>}
        </CardContent>
      </Card>
    </section>
    {!desktop && <FullCategoryBreakdown categories={categories} money={money} detailsId={detailsId}
      onSelect={(category, component) => { setBreakdownOpen(false); onSelect(category, component) }} />}
  </Sheet>
}

// Relative size of each category against the largest one, in the category's own colour.
function ShareBar({ category, percent }: { category: string; percent: number }) {
  return <span aria-hidden="true" className="ml-[2.375rem] mt-1 block h-1 overflow-hidden rounded-full bg-muted">
    <span className="block h-full rounded-full" style={{ width: `${Math.max(percent, 1.5)}%`, background: categoryColor(categoryMetadata(category)) }} />
  </span>
}

// Donut of each category's share of the positive total; credits that net below zero are listed but not drawn.
function CategoryDonut({ categories, field, title }: {
  categories: NetCategory[]; field: (typeof netColumns)[number]['field']; title: string
}) {
  const positive = categories.map(category => ({ category: category.category, value: Number(category[field]) }))
    .filter(entry => entry.value > 0)
  const total = positive.reduce((sum, entry) => sum + entry.value, 0)
  if (total <= 0) return null
  const percent = (value: number) => value / total * 100
  const format = (value: number) => `${percent(value) >= 99.95 || percent(value) < 0.05 ? percent(value).toFixed(0) : percent(value).toFixed(1)}%`
  const top = positive[0]
  let offset = 0
  const segments = positive.map(entry => {
    const length = percent(entry.value)
    const segment = { ...entry, length, offset }
    offset += length
    return segment
  })
  const negativeCount = categories.length - positive.length
  return <div className="flex items-center gap-4 px-4 pb-2 pt-1 sm:gap-5 sm:px-5">
    <svg role="img" viewBox="0 0 42 42" className="size-28 shrink-0 -rotate-90"
      aria-label={`Share of ${title} by category: ${positive.map(entry => `${categoryMetadata(entry.category).label} ${format(entry.value)}`).join(', ')}`}>
      <circle cx="21" cy="21" r="15.915" fill="none" stroke="hsl(var(--muted))" strokeWidth="5" />
      {segments.map(segment => <circle key={segment.category} cx="21" cy="21" r="15.915" fill="none" strokeWidth="5"
        stroke={categoryColor(categoryMetadata(segment.category))}
        strokeDasharray={`${segments.length > 1 ? Math.max(segment.length - 0.8, 0.2) : segment.length} 100`} strokeDashoffset={-segment.offset} />)}
    </svg>
    <div aria-hidden="true" className="min-w-0 text-sm">
      <p className="text-xs font-semibold text-muted-foreground">Largest share</p>
      <p className="money mt-0.5 text-xl font-bold">{format(top.value)}</p>
      <p className="truncate font-medium" title={categoryMetadata(top.category).label}>{categoryMetadata(top.category).label}</p>
      {negativeCount > 0 && <p className="mt-1 text-xs text-muted-foreground">{negativeCount} below zero not drawn</p>}
    </div>
  </div>
}

// One accounting disclosure view, independent of the primary metric selection.
function FullCategoryBreakdown({ categories, money, detailsId, onSelect }: {
  categories: NetCategory[]; money: (value: string) => string; detailsId: string
  onSelect: (category: string, component: SpendingComponent) => void
}) {
  const sheetDrilldown = useRef(false)
  const full = useMemo(() => [...categories].sort((a, b) => Number(b.net_spending) - Number(a.net_spending)
    || categoryMetadata(a.category).label.localeCompare(categoryMetadata(b.category).label)), [categories])
  function selectFromSheet(category: string, component: SpendingComponent) {
    sheetDrilldown.current = true
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
        <SheetDescription>Net = Gross − Refunds − Reimbursements − Card Benefits. Select an amount for its transactions.</SheetDescription>
      </SheetHeader>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        {full.map(category => <details key={category.category} className="group border-b last:border-b-0">
          <summary className="flex min-h-16 cursor-pointer list-none items-center justify-between gap-3 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
            <span className="min-w-0"><CategoryLabel category={category.category} /></span>
            <span className="flex shrink-0 items-center gap-2"><span className="money text-sm font-semibold">{money(category.net_spending)}</span>
              <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden="true" /></span>
          </summary>
          <CategoryBreakdownContent category={category} money={money} onSelect={selectFromSheet} />
        </details>)}
        {full.length === 0 && <p className="py-4 text-sm text-muted-foreground">No spending contributions this month.</p>}
      </div>
    </SheetContent>
}

// Both inline desktop disclosures and mobile disclosures use the source M3 values.
function CategoryBreakdownContent({ category, money, onSelect }: {
  category: NetCategory; money: (value: string) => string
  onSelect: (category: string, component: SpendingComponent) => void
}) {
  return <div className="flex flex-col gap-1 pb-4">
            {netColumns.map(value => <button type="button" key={value.key}
              aria-label={`${value.title} transactions for ${categoryMetadata(category.category).label}: ${money(category[value.field])}`}
              className="flex min-h-11 flex-wrap items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => onSelect(category.category, value.key)}>
              <span className="flex flex-col gap-0.5"><span>{value.label}</span><span className="text-xs text-muted-foreground">{category[value.count]} {category[value.count] === 1 ? 'transaction' : 'transactions'}</span></span>
              <span className="flex items-center gap-2"><span className="money">{money(category[value.field])}</span><ChevronRight className="size-4 text-muted-foreground" aria-hidden="true" /></span>
            </button>)}
          </div>
}
