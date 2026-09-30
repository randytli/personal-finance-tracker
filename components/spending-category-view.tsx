'use client'

import { Fragment, useEffect, useId, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { CategoryBadge, categoryMetadata } from '@/components/category-display'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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

  function toggle(category: string) { setExpandedCategory(current => current === category ? null : category) }

  return <Sheet open={!desktop && breakdownOpen} onOpenChange={setBreakdownOpen}>
    <section aria-labelledby={`${id}-title`} className="min-w-0">
      <Card className="overflow-hidden shadow-sm">
        <CardHeader className="gap-2 p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle><h2 id={`${id}-title`} className="text-lg">{column.title} by Category</h2></CardTitle>
            {!desktop && <SheetTrigger asChild><Button type="button" variant="outline" size="sm">View full breakdown</Button></SheetTrigger>}
          </div>
          <CardDescription>{desktop ? 'Expand a category for its breakdown, or select an amount for transactions.' : 'Select a category for its transactions.'} Credits use their own posted month and category.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {desktop ? <table aria-label={`${column.title} by Category`} className="w-full table-fixed text-sm">
            <thead className="border-t bg-muted/50 text-xs text-muted-foreground"><tr>
              <th scope="col" className="w-[44%] px-4 py-2 text-left font-medium">Category</th>
              <th scope="col" className="w-[32%] px-3 py-2 text-right font-medium">{column.title}</th>
              <th scope="col" className="px-4 py-2 text-right font-medium">Transactions</th>
            </tr></thead>
            <tbody>{included.map(category => <Fragment key={category.category}><tr data-category={category.category} tabIndex={0} aria-selected={selected(category.category)}
              className={cn('cursor-pointer border-t hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring', selected(category.category) && 'bg-accent/70')}
              onClick={() => toggle(category.category)}
              onKeyDown={event => { if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); toggle(category.category) } }}>
              <td className="px-4 py-3"><button type="button" aria-label={`Breakdown for ${categoryMetadata(category.category).label}`}
                aria-expanded={expandedCategory === category.category} aria-controls={`${id}-${category.category}-breakdown`}
                className="flex w-full items-center gap-2 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={event => { event.stopPropagation(); toggle(category.category) }}>
                <ChevronDown className={cn('size-4 shrink-0 text-muted-foreground', expandedCategory === category.category && 'rotate-180')} aria-hidden="true" />
                <CategoryBadge category={category.category} /></button></td>
              <td className="px-3 py-3 text-right"><button type="button"
                aria-label={`${column.title} transactions for ${categoryMetadata(category.category).label}: ${money(category[column.field])}`}
                className="rounded px-1 py-1 font-semibold tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={event => { event.stopPropagation(); onSelect(category.category, metric) }}>{money(category[column.field])}</button></td>
              <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">{category[column.count]}</td>
            </tr>{expandedCategory === category.category && <tr><td colSpan={3} className="border-t bg-muted/20 px-4 pt-2">
              <div id={`${id}-${category.category}-breakdown`} role="group" aria-label={`Breakdown for ${categoryMetadata(category.category).label}`}>
                <CategoryBreakdownContent category={category} money={money} onSelect={onSelect} />
              </div>
            </td></tr>}</Fragment>)}</tbody>
          </table> : <div className="border-t" aria-label={`${column.title} category list`}>
            {included.map(category => <button type="button" key={category.category} aria-pressed={selected(category.category)}
              className={cn('flex min-h-16 w-full flex-wrap items-center justify-between gap-3 border-b px-4 py-3 text-left last:border-b-0 hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring', selected(category.category) && 'bg-accent/70')}
              onClick={() => onSelect(category.category, metric)}>
              <span className="flex min-w-0 flex-col items-start gap-1"><CategoryBadge category={category.category} />
                <span className="text-xs text-muted-foreground">{category[column.count]} {category[column.count] === 1 ? 'transaction' : 'transactions'}</span></span>
              <span className="flex max-w-full shrink-0 items-center gap-2 [overflow-wrap:anywhere]"><span className="text-sm font-semibold tabular-nums">{money(category[column.field])}</span><ChevronRight className="size-4 text-muted-foreground" aria-hidden="true" /></span>
            </button>)}
          </div>}
          {included.length === 0 && <p className="p-4 text-sm text-muted-foreground">No {column.title.toLowerCase()} transactions this month.</p>}
        </CardContent>
      </Card>
    </section>
    {!desktop && <FullCategoryBreakdown categories={categories} money={money} detailsId={detailsId}
      onSelect={(category, component) => { setBreakdownOpen(false); onSelect(category, component) }} />}
  </Sheet>
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
          <summary className="flex min-h-16 flex-wrap cursor-pointer list-none items-center justify-between gap-3 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
            <span className="min-w-0"><CategoryBadge category={category.category} /></span>
            <span className="flex max-w-full shrink-0 items-center gap-2 [overflow-wrap:anywhere]"><span className="text-sm font-semibold tabular-nums">{money(category.net_spending)}</span>
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
              className="flex min-h-11 flex-wrap items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => onSelect(category.category, value.key)}>
              <span className="flex flex-col gap-0.5"><span>{value.label}</span><span className="text-xs text-muted-foreground">{category[value.count]} {category[value.count] === 1 ? 'transaction' : 'transactions'}</span></span>
              <span className="flex items-center gap-2"><span className="tabular-nums">{money(category[value.field])}</span><ChevronRight className="size-4 text-muted-foreground" aria-hidden="true" /></span>
            </button>)}
          </div>
}
