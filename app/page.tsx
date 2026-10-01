'use client'

import { apiFetch } from '@/lib/api'
import { Amount, ChartLegend, ChartMonthlyTotals, ChipRow, ControlField, LoadingState, PageHeader, PageNavigation, Pagination, SectionCard, SectionHeader, SelectAllBar, Statement, TransactionRow, chartTooltipStyle, compactMoney, fieldClassName, pageClassName, sheetClassName, useNarrowViewport } from '@/components/page-presentation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CircleAlert, CircleCheck, ListChecks } from 'lucide-react'
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
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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

function money(value: string) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value))
}

function currentMonth() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
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
  const [detailLoading, setDetailLoading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [optionsRetry, setOptionsRetry] = useState(0)
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
  const narrowViewport = useNarrowViewport()
  const labelOptions = useLabelOptions()
  const sync = useSyncRefresh()

  useEffect(() => {
    let active = true
    apiFetch('/api/pft/review/categories').then(response => response.ok ? response.json() : Promise.reject())
      .then(data => { if (active) setCategoryOptions(data.categories) })
      .catch(() => { if (active) setError('Category options could not be loaded.') })
    apiFetch('/api/pft/review/benefit-categories').then(response => response.ok ? response.json() : Promise.reject())
      .then(data => { if (active) setBenefitCategoryOptions(data.categories) })
      .catch(() => { if (active) setError('Benefit category options could not be loaded.') })
    return () => { active = false }
  }, [optionsRetry])

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
    setDetailLoading(true)
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
      .finally(() => { if (active) setDetailLoading(false) })
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
      const response = await apiFetch('/api/pft/review/transactions/bulk-edit', {
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
    month: value.month,
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

  const filterChip = 'capitalize'
  const summaryColor = { netSpending: 'hsl(var(--chart-3))', income: 'hsl(var(--chart-2))', netSavings: 'hsl(var(--chart-1))' }
  return (
    <>
    <PageNavigation current="Overview" />
    <main className={pageClassName}>
      <PageHeader title="Overview" description="Effective spending and savings across active institutions."
        actions={<>
          {monthly && !loading && <Button variant="outline" type="button" onClick={() => setDetailFilter({ transactionType: 'unclassified' })}>
            <ListChecks aria-hidden="true" />Needs Review ({monthly.unclassified_count})
          </Button>}
          <ControlField label="Month">
            <input className={fieldClassName} type="month" value={month} onChange={(event) => setMonth(event.target.value)} />
          </ControlField>
        </>} />

      <div className="mt-5"><SyncHealth status={sync.status} error={sync.error} onRetry={() => { void sync.check().catch(() => undefined) }} /></div>

      {error && <Alert role="alert" variant="destructive" className="mt-4"><CircleAlert aria-hidden="true" /><span className="min-w-0 flex-1">{error}</span> <Button type="button" variant="outline" size="sm" onClick={() => { setError(''); setOptionsRetry(value => value + 1); sync.invalidate() }}>Retry loading</Button></Alert>}
      {bulkStatus && <Alert role="status" variant="success" className="mt-4"><CircleCheck aria-hidden="true" />{bulkStatus}</Alert>}
      {categoryUndo && <Alert role="status" variant="info" className="mt-4">
        <CircleCheck aria-hidden="true" />Category saved.
        <Button type="button" variant="link" size="inline" disabled={categoryBusy} onClick={() => saveCategory(categoryUndo.detail, categoryUndo.previous, true)}>Undo category change</Button>
      </Alert>}
      {loading && <LoadingState label="Loading analytics…" rows={3} />}

      {monthly && !loading && (
        <>
          <section aria-label="Monthly financial summary" className={cn(sheetClassName, 'mt-6 grid gap-x-10 gap-y-6 p-3 sm:p-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] lg:px-7 lg:py-6')}>
            <div className="min-w-0">
              <h2 className="px-2 pb-1 font-serif text-[19px] font-semibold sm:px-3">Spending</h2>
              <p className="px-2 pb-2 text-[13px] text-muted-foreground sm:px-3">Select a line to break it down by category below.</p>
              <Statement label="Spending components" lines={[
                { label: 'Gross Spending', value: money(monthly.gross_spending), selected: categoryMode === 'gross', onClick: () => selectCategoryMode('gross') },
                { label: 'Refunds', operator: '−', value: money(monthly.refunds), selected: categoryMode === 'refunds', onClick: () => selectCategoryMode('refunds') },
                { label: 'Reimbursements', operator: '−', value: money(monthly.reimbursements), selected: categoryMode === 'reimbursements', onClick: () => selectCategoryMode('reimbursements') },
                { label: 'Card Benefits', operator: '−', value: money(monthly.card_benefits), selected: categoryMode === 'card_benefits', onClick: () => selectCategoryMode('card_benefits') },
              ]} total={{ label: 'Net Spending', value: money(monthly.net_spending), selected: categoryMode === 'net', onClick: () => selectCategoryMode('net') }} />
            </div>
            <div className="min-w-0 border-t pt-5 lg:border-l lg:border-t-0 lg:pl-10 lg:pt-0">
              <h2 className="px-2 pb-3 font-serif text-[19px] font-semibold sm:px-3">Savings</h2>
              <Statement label="Savings" lines={[
                { label: 'Income', value: money(monthly.income), onClick: () => setDetailFilter({ transactionType: 'income' }) },
                { label: 'Net Spending', operator: '−', value: money(monthly.net_spending) },
              ]} total={{ label: 'Net Savings', value: money(monthly.net_savings) }} />
            </div>
          </section>

          <section className="mt-10 grid items-start gap-x-8 gap-y-10 lg:grid-cols-2">
            <SectionCard plain aria-label="12-Month Trend" className="min-w-0">
              <SectionHeader plain title="12-Month Trend" description="Monthly totals in US dollars" />
              <div>
                <ChartLegend items={[{ label: 'Net Spending', color: summaryColor.netSpending }, { label: 'Income', color: summaryColor.income }, { label: 'Net Savings', color: summaryColor.netSavings }]} />
                <div className="mt-3 h-64 min-w-0 sm:h-72">
                  {chartData.length > 0 ? <ResponsiveContainer width="100%" height="100%">
                    <LineChart accessibilityLayer data={chartData} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
                      <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
                      <XAxis dataKey="month" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} minTickGap={narrowViewport ? 40 : 18} tickFormatter={value => value.slice(5)} />
                      <YAxis tickCount={narrowViewport ? 4 : 5} width={56} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} tickFormatter={compactMoney} />
                      <Tooltip trigger={narrowViewport ? 'click' : 'hover'} position={narrowViewport ? { x: 4, y: 4 } : undefined} wrapperStyle={{ maxWidth: 'calc(100% - 8px)' }} formatter={(value) => money(String(value))} contentStyle={chartTooltipStyle} />
                      <Line type="monotone" dataKey="netSpending" name="Net Spending" stroke={summaryColor.netSpending} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                      <Line type="monotone" dataKey="income" name="Income" stroke={summaryColor.income} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                      <Line type="monotone" dataKey="netSavings" name="Net Savings" stroke={summaryColor.netSavings} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                    </LineChart>
                  </ResponsiveContainer> : <p className="flex h-full items-center justify-center text-sm text-muted-foreground">No trend data for this period.</p>}
                </div>
                <ChartMonthlyTotals rows={chartData} columns={[{ key: 'netSpending', label: 'Net Spending' }, { key: 'income', label: 'Income' }, { key: 'netSavings', label: 'Net Savings' }]} money={money} />
              </div>
            </SectionCard>

            <SpendingCategoryView categories={monthly.category_net_breakdown || []} metric={categoryMode}
              selectedCategory={detailFilter?.canonicalCategory} selectedComponent={detailFilter?.spendingComponent}
              onSelect={(category, component) => setDetailFilter({ canonicalCategory: category, spendingComponent: component })}
              money={money} detailsId="overview-transaction-details" />
          </section>

          <SectionCard className="mt-10 overflow-hidden">
            <SectionHeader title={categoryMode === 'card_benefits' ? `Card Benefits by ${groupBy}`
              : categoryMode === 'reimbursements' ? `Reimbursements by ${groupBy}` : `Spending by ${groupBy}`}
              description={`Select a category above to filter these summaries by ${groupBy}.`}
              actions={<select aria-label="Group summary by" className={fieldClassName} value={groupBy} onChange={(event) => setGroupBy(event.target.value as 'institution' | 'account')}>
                <option value="institution">Institution</option><option value="account">Account</option>
              </select>} />
            <div className={cn('grid border-t', breakdown.length > 1 && 'sm:grid-cols-2')}>
              {breakdown.map((group) => (
                <button
                  type="button"
                  key={group.account_id || group.institution_id}
                  disabled={!detailFilter?.category && !detailFilter?.benefitCategory && !detailFilter?.canonicalCategory}
                  onClick={() => selectSecondary(group)}
                  aria-pressed={Boolean(detailFilter?.secondary && (group.account_id
                    ? detailFilter.secondary.account_id === group.account_id
                    : detailFilter.secondary.institution_id === group.institution_id))}
                  className={cn('flex min-w-0 flex-wrap items-center justify-between gap-3 border-b px-4 py-3.5 text-left transition-colors last:border-b-0 sm:px-5', breakdown.length > 1 && 'sm:border-r sm:even:border-r-0', 'enabled:hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
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
                    <span className="block text-[15px] font-semibold tabular-nums">{money(categoryMode === 'card_benefits' ? group.benefit_amount || group.card_benefits
                      : categoryMode === 'reimbursements' ? group.reimbursements : group.net_spending)}</span>
                    <span className="block text-xs text-muted-foreground">{categoryMode === 'card_benefits' ? 'card benefits'
                      : categoryMode === 'reimbursements' ? 'reimbursements' : 'net spending'}</span>
                  </span>
                </button>
              ))}
              {breakdown.length === 0 && <p className="px-4 py-3.5 text-sm text-muted-foreground sm:col-span-2 sm:px-5">No accounts contribute to this view.</p>}
            </div>
          </SectionCard>

          {detailFilter && (
            <div id="overview-transaction-details" ref={detailSection} tabIndex={-1} className="mt-10 scroll-mt-20 focus:outline-none">
            <SectionCard className="overflow-hidden">
              <div className="flex items-start justify-between gap-4 px-4 pb-4 pt-4 sm:px-5 sm:pt-5">
                <div className="min-w-0">
                  <h2 className="font-serif text-[19px] font-semibold leading-7">Transaction Details</h2>
                  <div aria-label="Active detail filters" className="mt-2 flex flex-wrap items-center gap-1.5 text-sm">
                    <Badge variant="secondary" className="tabular-nums">{month}</Badge>
                    {detailFilter.transactionType && <Badge variant="secondary" className={filterChip}>{detailFilter.transactionType.replace(/_/g, ' ')}</Badge>}
                    {detailFilter.spendingComponent && <Badge variant="secondary" className={filterChip}>{detailFilter.spendingComponent.replace(/_/g, ' ')}</Badge>}
                    {detailFilter.canonicalCategory
                      ? <CategoryBadge category={detailFilter.canonicalCategory} />
                      : detailFilter.category
                      ? <CategoryBadge category={detailFilter.category} />
                      : detailFilter.benefitCategory
                        ? <BenefitCategoryBadge category={detailFilter.benefitCategory} />
                        : null}
                    {detailFilter.secondary && (
                      <button type="button" className="rounded-md border border-primary/40 bg-info-soft px-2.5 py-1 text-xs font-medium text-primary hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => setDetailFilter({ ...detailFilter, secondary: undefined })}>
                        {detailFilter.secondary.institution_name}
                        {detailFilter.secondary.account_name ? ` · ${detailFilter.secondary.account_name} · ${detailFilter.secondary.account_mask || ''}` : ''}
                        {' · Clear ×'}
                      </button>
                    )}
                  </div>
                  <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
                    <p className="text-sm text-muted-foreground">{detailTotal} matching transactions</p>
                    {detailFilter.transactionType === 'reimbursement' &&
                      <p className="text-sm font-semibold tabular-nums">Total reimbursements: {money(detailReimbursements)}</p>}
                    {detailFilter.spendingComponent && <p className="text-sm font-semibold tabular-nums">
                      {detailFilter.spendingComponent === 'net' ? 'Net contribution' : netColumns.find(column => column.key === detailFilter.spendingComponent)?.label}: {' '}
                      {money(detailComponentTotals[detailFilter.spendingComponent === 'gross' ? 'gross_spending' : detailFilter.spendingComponent === 'net' ? 'net_spending' : detailFilter.spendingComponent] || '0.00')}
                    </p>}
                  </div>
                </div>
                <Button type="button" variant="outline" size="sm" onClick={() => { setDetailFilter(null); setSelectedDetails(new Set()) }}>Close</Button>
              </div>
              {details.length > 0 && <SelectAllBar>
                <label className="inline-flex items-center gap-2 text-sm font-medium">
                  <input type="checkbox"
                    checked={details.length > 0 && details.every(detail => selectedDetails.has(detail.transaction_id))}
                    ref={element => { if (element) element.indeterminate = selectedDetails.size > 0 && !details.every(detail => selectedDetails.has(detail.transaction_id)) }}
                    disabled={bulkBusy}
                    onChange={event => setSelectedDetails(event.target.checked
                      ? new Set(details.map(detail => detail.transaction_id)) : new Set())} />
                  Select all displayed ({details.length})
                </label>
              </SelectAllBar>}
              {detailLoading && <p role="status" className="border-t px-4 py-3.5 text-sm text-muted-foreground sm:px-5">Loading transaction details…</p>}
              {!detailLoading && details.length === 0 && !error && <p className="border-t px-4 py-3.5 text-sm text-muted-foreground sm:px-5">No matching transactions.</p>}
              <div className="divide-y border-t">
                {details.map((detail) => (
                  <TransactionRow key={detail.transaction_id}
                    select={<label>
                      <input type="checkbox" checked={selectedDetails.has(detail.transaction_id)}
                        disabled={bulkBusy} onChange={() => toggleDetail(detail.transaction_id)}
                        aria-label={`Select ${detail.merchant_name || detail.description || 'transaction'}`} />
                    </label>}
                    title={<p className="break-words font-medium">{detail.merchant_name || detail.description || 'Unknown transaction'}</p>}
                    date={detail.transaction_date}
                    meta={<>{detail.description} · <span className="capitalize">{detail.transaction_type.replace(/_/g, ' ')}</span></>}
                    amount={<>
                      <Amount value={detail.amount}>{money(detail.amount)}</Amount>
                      {detailFilter.spendingComponent === 'net' && detail.net_contribution && <p className="text-xs font-medium tabular-nums text-muted-foreground">Net contribution {money(detail.net_contribution)}</p>}
                    </>}>
                    <ChipRow>
                      {detail.institution_name && detail.account_name && (
                        <AccountBadge institutionName={detail.institution_name} accountName={detail.account_name} accountMask={detail.account_mask} accountType={detail.account_type || ''} accountSubtype={detail.account_subtype} />
                      )}
                      <CategoryEditor detail={detail} options={categoryOptions} busy={categoryBusy || bulkBusy} save={saveCategory} />
                      <BenefitCategoryEditor detail={detail} options={benefitCategoryOptions} disabled={bulkBusy} onChanged={changed => updateBenefitCategory(detail, changed)} />
                      <LabelEditor detail={detail} options={labelOptions.options}
                        optionsLoading={labelOptions.loading} optionsError={labelOptions.error}
                        disabled={bulkBusy} onRetryOptions={labelOptions.retry} onChanged={updateLabels} />
                    </ChipRow>
                  </TransactionRow>
                ))}
              </div>
              {selectedDetails.size > 0 && <div className="min-w-0">
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
                  errorMessage={error} onApply={applyBulk}
                  onClear={() => setSelectedDetails(new Set())}
                />
              </div>}
              {detailTotal > 100 && <Pagination className="border-t px-4 py-3 sm:px-5" offset={detailOffset} pageSize={100} total={detailTotal} onPage={setDetailOffset} />}
            </SectionCard>
            </div>
          )}
        </>
      )}

      <SectionCard plain aria-labelledby="connected-institutions" className="mt-12">
        <SectionHeader plain id="connected-institutions" title="Connected Institutions" />
        <div><PlaidLinkButton /></div>
      </SectionCard>
    </main>
    </>
  )
}
