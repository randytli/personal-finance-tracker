'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import AccountBadge from '@/components/account-badge'
import BulkTransactionEditor, { bulkErrorMessage, type BulkEditRequest } from '@/components/bulk-transaction-editor'
import CategoryEditor, { mergeCategoryDetail, mutateCategoryOverride, type CategoryDetail } from '@/components/category-editor'
import { BenefitCategoryBadge, CategoryBadge } from '@/components/category-display'
import InstitutionBadge from '@/components/institution-badge'
import LabelEditor, { mergeLabelDetail, type LabelDetail, useLabelOptions } from '@/components/label-editor'
import PlaidLinkButton from '@/components/plaid-link-button'
import { SyncHealth, consistentJson, useSyncRefresh } from '@/components/sync-health'
import BenefitCategoryEditor, { type BenefitCategoryOption, type BenefitCategoryDetail } from '@/components/benefit-category-editor'
import { Button } from '@/components/ui/button'
import { Card as SummaryCard, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import SpendingCategoryView, { netColumns, type NetCategory, type SpendingComponent } from '@/components/spending-category-view'

type Category = {
  category: string
  gross_spending: string
  refunds: string
  reimbursements: string
  net_spending: string
  spending_transaction_count: number
  expense_transaction_count: number
  refund_transaction_count: number
  reimbursement_transaction_count: number
}
type BenefitCategory = { benefit_category: string; benefit_amount: string; benefit_transaction_count: number }

type Monthly = {
  month: string
  gross_spending: string
  refunds: string
  reimbursements: string
  card_benefits: string
  net_spending: string
  income: string
  net_savings: string
  unclassified_count: number
  category_breakdown: Category[]
  benefit_category_breakdown: BenefitCategory[]
  category_attribution_version?: number
  category_net_breakdown?: NetCategory[]
}

type TrendMonth = { month: string; net_spending: string; income: string; net_savings: string }
type BreakdownGroup = {
  institution_id: string
  institution_name: string
  account_id?: string
  account_name?: string
  account_mask?: string | null
  account_type?: string
  account_subtype?: string | null
  gross_spending: string
  refunds: string
  reimbursements: string
  reimbursement_transaction_count: number
  card_benefits: string
  benefit_amount?: string
  benefit_transaction_count?: number
  net_spending: string
}
type Detail = CategoryDetail & LabelDetail & {
  transaction_id: string
  transaction_date: string
  institution_name: string | null
  account_name: string | null
  account_mask: string | null
  account_type: string | null
  account_subtype: string | null
  merchant_name: string | null
  description: string | null
  amount: string
  transaction_type: string
  is_internal_transfer: boolean | null
  plaid_category: string
  automatic_benefit_category: string | null
  override_benefit_category: string | null
  effective_benefit_category: string | null
  benefit_category_editable: boolean
  canonical_category?: string | null
  attribution_source?: string | null
  net_contribution?: string | null
}

function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-lg border bg-white shadow-sm ${className}`}>{children}</section>
}

function money(value: string) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value))
}

function compactMoney(value: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function currentMonth() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function MetricCard({ label, value, onClick, selected, primary = false }: {
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

export default function HomePage() {
  const [month, setMonth] = useState(currentMonth)
  const [monthly, setMonthly] = useState<Monthly | null>(null)
  const [trend, setTrend] = useState<TrendMonth[]>([])
  const [groupBy, setGroupBy] = useState<'institution' | 'account'>('institution')
  const [breakdown, setBreakdown] = useState<BreakdownGroup[]>([])
  const [categoryMode, setCategoryMode] = useState<SpendingComponent>('net')
  const [detailFilter, setDetailFilter] = useState<{
    category?: string; benefitCategory?: string; transactionType?: string; secondary?: BreakdownGroup
    canonicalCategory?: string; spendingComponent?: SpendingComponent
  } | null>(null)
  const [details, setDetails] = useState<Detail[]>([])
  const [detailTotal, setDetailTotal] = useState(0)
  const [detailReimbursements, setDetailReimbursements] = useState('0.00')
  const [detailComponentTotals, setDetailComponentTotals] = useState<Record<string, string>>({})
  const [detailOffset, setDetailOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [categoryOptions, setCategoryOptions] = useState<Array<{ value: string; label: string }>>([])
  const [benefitCategoryOptions, setBenefitCategoryOptions] = useState<BenefitCategoryOption[]>([])
  const [categoryBusy, setCategoryBusy] = useState(false)
  const [categoryRevision, setCategoryRevision] = useState(0)
  const [categoryUndo, setCategoryUndo] = useState<{ detail: CategoryDetail; previous: string | null } | null>(null)
  const [selectedDetails, setSelectedDetails] = useState<Set<string>>(new Set())
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkStatus, setBulkStatus] = useState('')
  const [detailRevision, setDetailRevision] = useState(0)
  const detailSection = useRef<HTMLDivElement>(null)
  const labelOptions = useLabelOptions()
  const sync = useSyncRefresh()

  useEffect(() => {
    let active = true
    fetch('/api/pft/review/categories').then(response => response.ok ? response.json() : Promise.reject())
      .then(data => { if (active) setCategoryOptions(data.categories) })
      .catch(() => { if (active) setError('Category options could not be loaded.') })
    fetch('/api/pft/review/benefit-categories').then(response => response.ok ? response.json() : Promise.reject())
      .then(data => { if (active) setBenefitCategoryOptions(data.categories) })
    return () => { active = false }
  }, [])

  function updateBenefitCategory(detail: Detail, changed: BenefitCategoryDetail) {
    setDetails(current => current.map(value => value.transaction_id === detail.transaction_id ? { ...value, ...changed } : value))
    setDetailRevision(value => value + 1)
    sync.invalidate()
  }

  async function saveCategory(detail: CategoryDetail, category: string | null, undo = false): Promise<boolean> {
    setCategoryBusy(true)
    setError('')
    try {
      const changed = await mutateCategoryOverride(detail.transaction_id, category)
      setCategoryUndo(undo ? null : { detail, previous: detail.override_category })
      setSelectedDetails(new Set())
      setDetails(current => current.map(value => mergeCategoryDetail(value, changed)))
      setCategoryRevision(value => value + 1)
      sync.invalidate()
      return true
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Category change failed.')
      return false
    } finally { setCategoryBusy(false) }
  }

  useEffect(() => { setDetailFilter(null); setSelectedDetails(new Set()) }, [month])

  const loadDashboard = useCallback(async (isActive: () => boolean) => {
    setLoading(true)
    setError('')
    try {
      const [monthlyData, trendData] = await consistentJson([
        `/api/pft/analytics/monthly?month=${month}`,
        `/api/pft/analytics/trend?end_month=${month}`,
      ], sync.check)
      if (!isActive()) return
      setMonthly(monthlyData)
      setTrend(trendData.months || [])
    } catch {
      if (isActive()) setError('Analytics could not be loaded. Confirm the local API is running.')
    } finally {
      if (isActive()) setLoading(false)
    }
  }, [month, sync.check])

  useEffect(() => {
    let active = true
    void loadDashboard(() => active)
    return () => { active = false }
  }, [loadDashboard, categoryRevision, sync.revision])

  useEffect(() => {
    let active = true
    setBreakdown([])
    const breakdownMode = categoryMode === 'card_benefits' ? 'benefits'
      : categoryMode === 'reimbursements' ? 'reimbursements' : 'spending'
    consistentJson([`/api/pft/analytics/breakdown?month=${month}&group_by=${groupBy}&mode=${breakdownMode}`], sync.check)
      .then(([data]) => { if (active) setBreakdown(data.groups || []) })
      .catch(() => { if (active) setError('Spending breakdown could not be loaded.') })
    return () => { active = false }
  }, [month, groupBy, categoryMode, sync.revision, sync.check])

  useEffect(() => {
    if (!detailFilter) return
    let active = true
    setDetails([])
    setDetailTotal(0)
    const parameters = new URLSearchParams({ month, limit: '100', offset: String(detailOffset) })
    if (detailFilter.category) parameters.set('category', detailFilter.category)
    if (detailFilter.canonicalCategory) parameters.set('canonical_category', detailFilter.canonicalCategory)
    if (detailFilter.spendingComponent) parameters.set('spending_component', detailFilter.spendingComponent)
    if (detailFilter.benefitCategory) parameters.set('benefit_category', detailFilter.benefitCategory)
    if (detailFilter.transactionType) parameters.set('transaction_type', detailFilter.transactionType)
    if ((detailFilter.category || detailFilter.benefitCategory || detailFilter.canonicalCategory) && detailFilter.secondary) {
      parameters.set('institution_id', detailFilter.secondary.institution_id)
      if (detailFilter.secondary.account_id) parameters.set('account_id', detailFilter.secondary.account_id)
    }
    consistentJson([`/api/pft/analytics/transactions?${parameters}`], sync.check)
      .then(([data]) => {
        if (!active) return
        setDetails(data.transactions || [])
        setSelectedDetails(new Set())
        setDetailTotal(data.total || 0)
        setDetailReimbursements(data.reimbursements || '0.00')
        setDetailComponentTotals(data.component_totals || {})
      })
      .catch(() => { if (active) setError('Transaction details could not be loaded.') })
    return () => { active = false }
  }, [detailFilter, detailOffset, month, categoryRevision, detailRevision, sync.revision, sync.check])

  useEffect(() => { setSelectedDetails(new Set()); setDetailOffset(0) }, [detailFilter])

  useEffect(() => {
    if (detailFilter) detailSection.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }, [detailFilter])

  function updateLabels(changed: LabelDetail) {
    setDetails(current => current.map(detail => mergeLabelDetail(detail, changed)))
    sync.invalidate()
  }

  async function applyBulk(request: BulkEditRequest) {
    setBulkBusy(true)
    setError('')
    setBulkStatus('')
    try {
      const response = await fetch('/api/pft/review/transactions/bulk-edit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
      })
      const body = await response.json().catch(() => null)
      if (!response.ok) throw new Error(bulkErrorMessage(body))
      setSelectedDetails(new Set())
      setBulkStatus(`${body.changed_count} changed · ${body.unchanged_count} unchanged.`)
      setCategoryRevision(value => value + 1)
      setDetailRevision(value => value + 1)
      sync.invalidate()
      return true
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Bulk change could not be saved.')
      return false
    } finally { setBulkBusy(false) }
  }

  function toggleDetail(transactionId: string) {
    setSelectedDetails(current => {
      const next = new Set(current)
      if (next.has(transactionId)) next.delete(transactionId)
      else next.add(transactionId)
      return next
    })
  }

  const selectedDetailsRows = details.filter(detail => selectedDetails.has(detail.transaction_id))
  const classificationOptions = [
    { value: 'reimbursement' as const, label: 'Reimbursement', eligibleCount: selectedDetailsRows.filter(detail => Number(detail.amount) > 0 && detail.is_internal_transfer !== true).length },
    { value: 'expense' as const, label: 'Expense', eligibleCount: selectedDetailsRows.filter(detail => Number(detail.amount) < 0 && detail.is_internal_transfer !== true).length },
  ]

  const chartData = useMemo(() => trend.map((value) => ({
    month: value.month.slice(5),
    netSpending: Number(value.net_spending),
    income: Number(value.income),
    netSavings: Number(value.net_savings),
  })), [trend])
  function selectCategoryMode(mode: SpendingComponent) {
    setCategoryMode(mode)
    setDetailFilter(null)
    setDetails([])
    setDetailTotal(0)
    setSelectedDetails(new Set())
  }

  function selectSecondary(group: BreakdownGroup) {
    setDetailFilter((current) => {
      if (!current?.category && !current?.benefitCategory && !current?.canonicalCategory) return current
      const selected = current.secondary
      const same = group.account_id
        ? selected?.account_id === group.account_id
        : selected?.institution_id === group.institution_id
      return { ...current, secondary: same ? undefined : group }
    })
  }

  return (
    <main className="mx-auto max-w-7xl px-4 pb-10 pt-4 sm:px-6 sm:pt-6">
      <nav aria-label="Main navigation" className="flex flex-wrap items-center gap-2 border-b pb-3 sm:gap-4">
        <Link href="/" className="mr-auto text-base font-semibold tracking-tight">PFT</Link>
        <div className="flex items-center gap-1">
          <Button asChild variant="secondary" size="sm"><Link href="/" aria-current="page">Overview</Link></Button>
          <Button asChild variant="ghost" size="sm"><Link href="/review">Review</Link></Button>
          <Button asChild variant="ghost" size="sm"><Link href="/memberships">Memberships</Link></Button>
        </div>
      </nav>
      <header className="mt-6 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-3xl font-semibold tracking-tight">Overview</h1>
          <p className="mt-1 text-sm text-muted-foreground">Effective spending and savings across active institutions.</p>
        </div>
        <div className="flex w-full flex-wrap items-end gap-3 sm:w-auto">
          {monthly && !loading && <Button variant="outline" size="sm" type="button" onClick={() => setDetailFilter({ transactionType: 'unclassified' })}>
            Needs Review ({monthly.unclassified_count})
          </Button>}
          <label className="flex items-center gap-2 text-sm font-medium">
            Month
            <input
              className="min-h-9 rounded-md border bg-background px-2 py-1.5"
              type="month"
              value={month}
              onChange={(event) => setMonth(event.target.value)}
            />
          </label>
        </div>
      </header>

      <div className="mt-4"><SyncHealth status={sync.status} error={sync.error} /></div>

      {error && <p role="alert" className="mt-6 rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {bulkStatus && <p role="status" className="mt-6 rounded-md border bg-slate-50 p-3 text-sm">{bulkStatus}</p>}
      {categoryUndo && <p role="status" className="mt-4 rounded border p-3 text-sm">
        Category saved.
        <button type="button" className="ml-2 text-blue-700 underline" disabled={categoryBusy} onClick={() => saveCategory(categoryUndo.detail, categoryUndo.previous, true)}>Undo category change</button>
      </p>}
      {loading && <p className="mt-8 text-muted-foreground">Loading analytics…</p>}

      {monthly && !loading && (
        <>
          <section aria-label="Monthly financial summary" className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4">
            <div className="col-span-2 sm:col-span-1"><MetricCard label="Net Spending" value={money(monthly.net_spending)} selected={categoryMode === 'net'} onClick={() => selectCategoryMode('net')} primary /></div>
            <MetricCard label="Income" value={money(monthly.income)} onClick={() => setDetailFilter({ transactionType: 'income' })} primary />
            <MetricCard label="Net Savings" value={money(monthly.net_savings)} primary />
          </section>
          <section aria-label="Spending components" className="mt-3 grid grid-cols-2 gap-3 sm:mt-4 sm:gap-4 lg:grid-cols-4">
            <MetricCard label="Gross Spending" value={money(monthly.gross_spending)} selected={categoryMode === 'gross'} onClick={() => selectCategoryMode('gross')} />
            <MetricCard label="Refunds" value={money(monthly.refunds)} selected={categoryMode === 'refunds'} onClick={() => selectCategoryMode('refunds')} />
            <MetricCard label="Reimbursements" value={money(monthly.reimbursements)} selected={categoryMode === 'reimbursements'} onClick={() => selectCategoryMode('reimbursements')} />
            <MetricCard label="Card Benefits" value={money(monthly.card_benefits)} selected={categoryMode === 'card_benefits'} onClick={() => selectCategoryMode('card_benefits')} />
          </section>
          <p className="mt-3 text-sm text-muted-foreground">Net Spending = Gross Spending − Refunds − Reimbursements − Card Benefits.</p>

          <section className="mt-8 grid gap-6 lg:grid-cols-2">
            <Card className="min-w-0 p-4 sm:p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h2 className="text-lg font-semibold">12-Month Trend</h2>
                <p className="text-xs text-muted-foreground">Monthly totals · USD</p>
              </div>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Trend series">
                <span><span className="mr-1.5 inline-block size-2 rounded-full bg-destructive" />Net Spending</span>
                <span><span className="mr-1.5 inline-block size-2 rounded-full bg-primary" />Income</span>
                <span><span className="mr-1.5 inline-block size-2 rounded-full bg-foreground" />Net Savings</span>
              </div>
              <div className="mt-4 h-64 min-w-0 sm:h-72">
                {chartData.length > 0 ? <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
                    <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
                    <XAxis dataKey="month" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} minTickGap={18} />
                    <YAxis width={48} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} tickFormatter={compactMoney} />
                    <Tooltip formatter={(value) => money(String(value))} contentStyle={{ borderRadius: 8, borderColor: 'hsl(var(--border))' }} />
                    <Line type="monotone" dataKey="netSpending" name="Net Spending" stroke="hsl(var(--destructive))" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                    <Line type="monotone" dataKey="income" name="Income" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                    <Line type="monotone" dataKey="netSavings" name="Net Savings" stroke="hsl(var(--foreground))" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                  </LineChart>
                </ResponsiveContainer> : <p className="flex h-full items-center justify-center text-sm text-muted-foreground">No trend data for this period.</p>}
              </div>
            </Card>

            <SpendingCategoryView categories={monthly.category_net_breakdown || []} metric={categoryMode}
              selectedCategory={detailFilter?.canonicalCategory} selectedComponent={detailFilter?.spendingComponent}
              onSelect={(category, component) => setDetailFilter({ canonicalCategory: category, spendingComponent: component })}
              money={money} detailsId="overview-transaction-details" />
          </section>

          <Card className="mt-6 overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 p-4 sm:p-5">
              <h2 className="text-lg font-semibold">{categoryMode === 'card_benefits' ? `Card Benefits by ${groupBy}`
                : categoryMode === 'reimbursements' ? `Reimbursements by ${groupBy}` : `Spending by ${groupBy}`}</h2>
              <select aria-label="Group summary by" className="min-h-9 rounded-md border bg-background px-3 py-2 text-sm" value={groupBy} onChange={(event) => setGroupBy(event.target.value as 'institution' | 'account')}>
                <option value="institution">Institution</option><option value="account">Account</option>
              </select>
            </div>
            <p className="px-4 pb-3 text-xs text-muted-foreground sm:px-5">Select a category above to filter these summaries by {groupBy}.</p>
            <div className="grid border-t sm:grid-cols-2">
              {breakdown.map((group) => (
                <button
                  type="button"
                  key={group.account_id || group.institution_id}
                  disabled={!detailFilter?.category && !detailFilter?.benefitCategory && !detailFilter?.canonicalCategory}
                  onClick={() => selectSecondary(group)}
                  aria-pressed={Boolean(detailFilter?.secondary && (group.account_id
                    ? detailFilter.secondary.account_id === group.account_id
                    : detailFilter.secondary.institution_id === group.institution_id))}
                  className={cn('flex min-w-0 items-center justify-between gap-3 border-b p-4 text-left transition-colors last:border-b-0 sm:border-r sm:even:border-r-0 enabled:hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                    detailFilter?.secondary && (group.account_id
                      ? detailFilter.secondary.account_id === group.account_id
                      : detailFilter.secondary.institution_id === group.institution_id) && 'bg-accent/70 ring-2 ring-inset ring-ring')}
                >
                  <span className="min-w-0">
                    {group.account_name ? (
                      <AccountBadge institutionName={group.institution_name} accountName={group.account_name} accountMask={group.account_mask || null} accountType={group.account_type || ''} accountSubtype={group.account_subtype} />
                    ) : <InstitutionBadge institutionName={group.institution_name} />}
                    {group.account_name && <span className="mt-1 block truncate text-xs text-muted-foreground">{group.institution_name}</span>}
                  </span>
                  <span className="shrink-0 text-right">
                    <span className="block font-semibold tabular-nums">{money(categoryMode === 'card_benefits' ? group.benefit_amount || group.card_benefits
                      : categoryMode === 'reimbursements' ? group.reimbursements : group.net_spending)}</span>
                    <span className="block text-xs text-muted-foreground">{categoryMode === 'card_benefits' ? 'card benefits'
                      : categoryMode === 'reimbursements' ? 'reimbursements' : 'net spending'}</span>
                  </span>
                </button>
              ))}
            </div>
          </Card>

          {detailFilter && (
            <div id="overview-transaction-details" ref={detailSection} tabIndex={-1} className="mt-6 scroll-mt-4 focus:outline-none">
            <Card className="overflow-hidden ring-1 ring-ring/30">
              <div className="flex items-start justify-between gap-4 p-4 sm:p-5">
                <div className="min-w-0">
                  <h2 className="text-lg font-semibold">Transaction Details</h2>
                  <div aria-label="Active detail filters" className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                    <span className="rounded-full bg-secondary px-2.5 py-1 text-xs font-medium text-secondary-foreground">{month}</span>
                    {detailFilter.transactionType && <span className="rounded-full bg-secondary px-2.5 py-1 text-xs font-medium capitalize text-secondary-foreground">{detailFilter.transactionType.replace(/_/g, ' ')}</span>}
                    {detailFilter.spendingComponent && <span className="rounded-full bg-secondary px-2.5 py-1 text-xs font-medium capitalize text-secondary-foreground">{detailFilter.spendingComponent.replace(/_/g, ' ')}</span>}
                    {detailFilter.canonicalCategory
                      ? <CategoryBadge category={detailFilter.canonicalCategory} />
                      : detailFilter.category
                      ? <CategoryBadge category={detailFilter.category} />
                      : detailFilter.benefitCategory
                        ? <BenefitCategoryBadge category={detailFilter.benefitCategory} />
                        : null}
                    {detailFilter.secondary && (
                      <button type="button" className="rounded-full border border-primary px-2.5 py-1 text-xs font-medium text-primary hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => setDetailFilter({ ...detailFilter, secondary: undefined })}>
                        {detailFilter.secondary.institution_name}
                        {detailFilter.secondary.account_name ? ` · ${detailFilter.secondary.account_name} · ${detailFilter.secondary.account_mask || ''}` : ''}
                        {' · Clear ×'}
                      </button>
                    )}
                  </div>
                  <p className="mt-2 text-sm text-muted-foreground">{detailTotal} matching transactions</p>
                  {detailFilter.transactionType === 'reimbursement' &&
                    <p className="text-sm font-medium text-slate-700">Total reimbursements: {money(detailReimbursements)}</p>}
                  {detailFilter.spendingComponent && <p className="text-sm font-medium text-slate-700">
                    {detailFilter.spendingComponent === 'net' ? 'Net contribution' : netColumns.find(column => column.key === detailFilter.spendingComponent)?.label}: {' '}
                    {money(detailComponentTotals[detailFilter.spendingComponent === 'gross' ? 'gross_spending' : detailFilter.spendingComponent === 'net' ? 'net_spending' : detailFilter.spendingComponent] || '0.00')}
                  </p>}
                </div>
                <Button type="button" variant="ghost" size="sm" onClick={() => { setDetailFilter(null); setSelectedDetails(new Set()) }}>Close</Button>
              </div>
              {details.length > 0 && <div className="border-t bg-slate-50 px-4 py-3">
                <label className="inline-flex items-center gap-2 text-sm font-medium">
                  <input type="checkbox"
                    checked={details.length > 0 && details.every(detail => selectedDetails.has(detail.transaction_id))}
                    ref={element => { if (element) element.indeterminate = selectedDetails.size > 0 && !details.every(detail => selectedDetails.has(detail.transaction_id)) }}
                    disabled={bulkBusy}
                    onChange={event => setSelectedDetails(event.target.checked
                      ? new Set(details.map(detail => detail.transaction_id)) : new Set())} />
                  Select all displayed ({details.length})
                </label>
              </div>}
              <div className="divide-y">
                {details.map((detail) => (
                  <div key={detail.transaction_id} className="flex flex-wrap items-start justify-between gap-3 p-4">
                    <label className="pt-1">
                      <input type="checkbox" checked={selectedDetails.has(detail.transaction_id)}
                        disabled={bulkBusy} onChange={() => toggleDetail(detail.transaction_id)}
                        aria-label={`Select ${detail.merchant_name || detail.description || 'transaction'}`} />
                    </label>
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">{detail.merchant_name || detail.description || 'Unknown transaction'}</p>
                      <p className="text-sm text-muted-foreground">{detail.transaction_date} · {detail.description} · {detail.transaction_type.replace(/_/g, ' ')}</p>
                      {detail.institution_name && detail.account_name && (
                        <div className="mt-2"><AccountBadge institutionName={detail.institution_name} accountName={detail.account_name} accountMask={detail.account_mask} accountType={detail.account_type || ''} accountSubtype={detail.account_subtype} /></div>
                      )}
                    </div>
                    <p className="font-semibold">{money(detail.amount)}</p>
                    {detailFilter.spendingComponent === 'net' && detail.net_contribution && <p className="w-full text-right text-sm font-medium tabular-nums">Net contribution {money(detail.net_contribution)}</p>}
                    <div className="grid w-full gap-x-5 md:grid-cols-2">
                      <CategoryEditor detail={detail} options={categoryOptions} busy={categoryBusy || bulkBusy} save={saveCategory} />
                      <BenefitCategoryEditor detail={detail} options={benefitCategoryOptions} disabled={bulkBusy} onChanged={changed => updateBenefitCategory(detail, changed)} />
                      <LabelEditor detail={detail} options={labelOptions.options}
                        optionsLoading={labelOptions.loading} optionsError={labelOptions.error}
                        disabled={bulkBusy} onRetryOptions={labelOptions.retry} onChanged={updateLabels} />
                    </div>
                  </div>
                ))}
              </div>
              {selectedDetails.size > 0 && <div className="h-64 sm:h-32">
                <BulkTransactionEditor
                  transactionIds={Array.from(selectedDetails)}
                  categoryOptions={categoryOptions}
                  benefitCategoryOptions={benefitCategoryOptions}
                  labelOptions={labelOptions.options}
                  allowClassification
                  classificationOptions={classificationOptions}
                  allowCategory
                  categoryIneligibleCount={details.filter(detail => selectedDetails.has(detail.transaction_id) && !detail.category_editable).length}
                  allowBenefitCategory
                  benefitIneligibleCount={selectedDetailsRows.filter(detail => !detail.benefit_category_editable).length}
                  busy={bulkBusy}
                  onApply={applyBulk}
                  onClear={() => setSelectedDetails(new Set())}
                />
              </div>}
              {detailTotal > 100 && <div className="flex items-center gap-4 border-t p-4 text-sm">
                <button type="button" disabled={detailOffset === 0}
                  className="disabled:opacity-40" onClick={() => setDetailOffset(Math.max(0, detailOffset - 100))}>Previous</button>
                <span>{detailOffset + 1}–{Math.min(detailOffset + 100, detailTotal)} of {detailTotal}</span>
                <button type="button" disabled={detailOffset + 100 >= detailTotal}
                  className="disabled:opacity-40" onClick={() => setDetailOffset(detailOffset + 100)}>Next</button>
              </div>}
            </Card>
            </div>
          )}
        </>
      )}

      <Card className="mt-8 p-5">
        <h2 className="font-semibold">Connected Institutions</h2>
        <div className="mt-3"><PlaidLinkButton /></div>
      </Card>
    </main>
  )
}
