'use client'

import { Amount, ChartLegend, ChartMonthlyTotals, ChipRow, ControlField, DayGroup, LoadingState, MoreTags, PageHeader, PageNavigation, Pagination, SectionCard, SectionHeader, SelectAllBar, Sparkline, SummaryCard, TransactionRow, chartAxisTick, chartTooltipStyle, fieldClassName, groupByDay, pageClassName, quietLinkClassName, signedDisplay, trackingCallout, trackingCaption, trackingColor, trackingGradient, trackingText, trendTracking, useNarrowViewport, useTransactionPageSize } from '@/components/page-presentation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDownRight, ArrowUpRight, ChevronRight, CircleAlert, CircleCheck } from 'lucide-react'
import {
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
import LabelManager from '@/components/label-manager'
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

type TrendMonth = { month: string; net_spending: string; income: string; net_savings: string; reimbursements?: string }
type MonthlyField = 'net_spending' | 'gross_spending' | 'refunds' | 'reimbursements' | 'card_benefits'

// Summary cards in display order. Net Spending and Reimbursements have 12-month values in the
// trend payload; the other components read the existing monthly summaries when selected.
const SUMMARY_METRICS: Array<{ key: SpendingComponent; label: string; field: MonthlyField; trendKey?: 'net_spending' | 'reimbursements'; higherIsBetter: boolean }> = [
  { key: 'net', label: 'Net Spending', field: 'net_spending', trendKey: 'net_spending', higherIsBetter: false },
  { key: 'gross', label: 'Gross Spending', field: 'gross_spending', higherIsBetter: false },
  { key: 'refunds', label: 'Refunds', field: 'refunds', higherIsBetter: true },
  { key: 'reimbursements', label: 'Reimbursements', field: 'reimbursements', trendKey: 'reimbursements', higherIsBetter: true },
  { key: 'card_benefits', label: 'Card Benefits', field: 'card_benefits', higherIsBetter: true },
]
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
    canonicalCategory?: string; spendingComponent?: SpendingComponent; label?: string
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
  const detailPageSize = useTransactionPageSize() === 10 ? 10 : 100
  const labelOptions = useLabelOptions()
  const sync = useSyncRefresh()

  useEffect(() => {
    let active = true
    fetch('/api/pft/review/categories').then(response => response.ok ? response.json() : Promise.reject())
      .then(data => { if (active) setCategoryOptions(data.categories) })
      .catch(() => { if (active) setError('Category options could not be loaded.') })
    fetch('/api/pft/review/benefit-categories').then(response => response.ok ? response.json() : Promise.reject())
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
    const parameters = new URLSearchParams({ month, limit: String(detailPageSize), offset: String(detailOffset) })
    if (detailFilter.label) parameters.set('label', detailFilter.label)
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
  }, [detailFilter, detailOffset, detailPageSize, month, categoryRevision, detailRevision, sync.revision, sync.check])

  useEffect(() => { setSelectedDetails(new Set()); setDetailOffset(0) }, [detailFilter, detailPageSize])

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

  const selectedMetric = SUMMARY_METRICS.find(option => option.key === categoryMode)!
  const metricTrendKey = selectedMetric.trendKey
  const [componentHistory, setComponentHistory] = useState<{ trend: TrendMonth[]; months: Record<string, Monthly> } | null>(null)
  const [historyError, setHistoryError] = useState(false)
  const [historyRetry, setHistoryRetry] = useState(0)

  // Components without trend values load the same months' summaries from the monthly endpoint,
  // only while one of them is selected. Failures stay inside the trend card.
  useEffect(() => {
    if (metricTrendKey || trend.length === 0 || componentHistory?.trend === trend) return
    let active = true
    setHistoryError(false)
    const months = trend.map(value => value.month)
    consistentJson(months.map(value => `/api/pft/analytics/monthly?month=${value}`), sync.check)
      .then(data => { if (active) setComponentHistory({ trend, months: Object.fromEntries(months.map((value, index) => [value, data[index]])) }) })
      .catch(() => { if (active) setHistoryError(true) })
    return () => { active = false }
  }, [metricTrendKey, trend, componentHistory, historyRetry, sync.check])

  const series = useMemo(() => trend.map(value => metricTrendKey
    ? Number(value[metricTrendKey] ?? NaN)
    : componentHistory?.trend === trend ? Number(componentHistory.months[value.month]?.[selectedMetric.field] ?? NaN) : NaN),
  [trend, metricTrendKey, componentHistory, selectedMetric.field])
  const seriesReady = series.length > 0 && series.every(Number.isFinite)
  const tracking = useMemo(() => seriesReady ? trendTracking(series, selectedMetric.higherIsBetter) : null, [series, seriesReady, selectedMetric.higherIsBetter])
  const chartData = useMemo(() => trend.map((value, index) => ({
    month: value.month,
    value: series[index],
    netSpending: Number(value.net_spending),
    income: Number(value.income),
    netSavings: Number(value.net_savings),
    average: tracking?.average ?? 0,
  })), [trend, series, tracking])
  // The trend ends at the selected month, so the entry before it is last month.
  const lastMonthIndex = trend.length > 1 && trend.at(-1)?.month === month ? trend.length - 2 : -1
  const lastMonth = lastMonthIndex >= 0 ? trend[lastMonthIndex] : undefined
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
  const netSavings = Number(monthly?.net_savings ?? 0)
  const totalsColumns = [{ key: 'netSpending', label: 'Net Spending' }, { key: 'income', label: 'Income' }, { key: 'netSavings', label: 'Net Savings' }]
  return (
    <>
    <PageNavigation current="Overview" />
    <main className={pageClassName}>
      <PageHeader title="Overview" description="Effective spending and savings across active institutions."
        actions={<>
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
      <section aria-label="Transaction label controls" className="mt-4 flex flex-wrap items-end gap-3">
        <ControlField label="Transaction label">
          <select aria-label="Transaction label filter" className={fieldClassName} value={detailFilter?.label || ''}
            disabled={bulkBusy || labelOptions.loading} onChange={event => {
              const label = event.target.value
              setDetailFilter(label ? { label } : null)
            }}>
            <option value="">Choose a label</option>
            {labelOptions.options.map(option => <option key={option.value} value={option.value}>{option.label}{option.archived ? ' (archived)' : ''}</option>)}
          </select>
        </ControlField>
        <LabelManager options={labelOptions.options} loading={labelOptions.loading} optionsError={labelOptions.error} onRetry={labelOptions.retry} />
        {labelOptions.error && <p role="alert" className="text-sm text-destructive">{labelOptions.error}</p>}
      </section>
      {loading && <LoadingState label="Loading analytics…" rows={3} />}

      {monthly && !loading && (
        <>
          <section aria-label="Monthly financial summary" className="mt-6">
            <div className="grid grid-cols-1 gap-3 min-[380px]:grid-cols-2 md:grid-cols-4 min-[1400px]:grid-cols-[minmax(0,1.45fr)_repeat(4,minmax(0,1fr))]">
              {SUMMARY_METRICS.map(option => <SummaryCard key={option.key} label={option.label} value={money(monthly[option.field])}
                selected={categoryMode === option.key} onClick={() => selectCategoryMode(option.key)} primary={option.key === 'net'}
                className={option.key === 'net' ? 'min-[380px]:col-span-2 md:col-span-4 min-[1400px]:col-span-1' : undefined} />)}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">Net Spending = Gross Spending − Refunds − Reimbursements − Card Benefits.</p>
          </section>

          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
            <SectionCard aria-label="12-month trend" className="min-w-0 sm:col-span-2 lg:col-span-1 lg:row-span-2">
              <SectionHeader title={`${selectedMetric.label} trend`} description="Last 12 months" actions={<button type="button" className={quietLinkClassName}
                onClick={() => setDetailFilter({ transactionType: 'unclassified' })}>Needs Review ({monthly.unclassified_count})<ChevronRight aria-hidden="true" /></button>} />
              <div className="flex flex-col items-center px-4 text-center">
                <p className="money text-[26px] font-bold leading-tight tracking-tight min-[380px]:text-[30px]">{money(monthly[selectedMetric.field])}</p>
                <p className="text-sm font-semibold text-muted-foreground">{selectedMetric.label} this month</p>
                {lastMonthIndex >= 0 && Number.isFinite(series[lastMonthIndex]) && <p className="mt-1 text-sm font-medium text-info"><span className="money">{money(String(series[lastMonthIndex]))}</span> last month</p>}
              </div>
              <div className="px-2 pt-2 sm:px-4">
                <div className="h-48 min-w-0 sm:h-56">
                  {chartData.length > 0 && tracking ? <ResponsiveContainer width="100%" height="100%">
                    <LineChart accessibilityLayer data={chartData} margin={{ top: 16, right: 12, bottom: 0, left: 0 }}>
                      {trackingGradient(`${categoryMode}-tracking`, tracking)}
                      <XAxis dataKey="month" tickLine={false} axisLine={false} tick={chartAxisTick} minTickGap={narrowViewport ? 40 : 18} tickFormatter={value => value.slice(5)} />
                      <YAxis hide domain={['auto', 'auto']} />
                      <Tooltip trigger={narrowViewport ? 'click' : 'hover'} position={narrowViewport ? { x: 4, y: 4 } : undefined} wrapperStyle={{ maxWidth: 'calc(100% - 8px)' }} formatter={(value) => money(String(value))} contentStyle={chartTooltipStyle} cursor={{ stroke: 'hsl(var(--border))' }} />
                      <Line type="monotone" dataKey="average" name="12-month average" stroke="hsl(var(--muted-foreground))" strokeOpacity={0.6} strokeWidth={1.5} strokeDasharray="4 5" dot={false} activeDot={false} tooltipType="none" isAnimationActive={false} />
                      <Line type="monotone" dataKey="value" name={selectedMetric.label} stroke={tracking.flat ? trackingColor[tracking.tone] : `url(#${categoryMode}-tracking)`} strokeWidth={3} strokeLinecap="round"
                        dot={trackingCallout(chartData.length - 1, tracking)} activeDot={{ r: 5 }} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer> : <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
                    {chartData.length === 0 ? 'No trend data for this period.'
                      : historyError ? <>
                        <span>The 12-month {selectedMetric.label} history could not be loaded.</span>
                        <Button type="button" variant="outline" size="sm" onClick={() => { setComponentHistory(null); setHistoryRetry(value => value + 1) }}>Retry history</Button>
                      </> : <span role="status">Loading 12-month {selectedMetric.label} history…</span>}
                  </div>}
                </div>
                <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-2">
                  <ChartLegend items={[{ label: selectedMetric.label, color: tracking ? trackingColor[tracking.tone] : 'hsl(var(--chart-1))' }, { label: '12-month average', color: 'hsl(var(--muted-foreground))', dashed: true }]} />
                  {tracking && <p className="text-xs font-semibold" style={{ color: trackingColor[tracking.tone] }}>Latest month: {trackingText(tracking).replace(' avg', ' average')}</p>}
                </div>
                {tracking && <p className="mt-1 px-2 text-xs text-muted-foreground">{trackingCaption(tracking)}</p>}
                <div className="px-2 pb-4"><ChartMonthlyTotals rows={chartData}
                  columns={selectedMetric.key !== 'net' && seriesReady ? [{ key: 'value', label: selectedMetric.label }, ...totalsColumns] : totalsColumns} money={money} /></div>
              </div>
            </SectionCard>

            <SectionCard aria-label="Income" className="flex min-w-0 flex-col p-4 sm:p-5">
              <button type="button" onClick={() => setDetailFilter({ transactionType: 'income' })}
                className="-m-2 flex flex-col items-start rounded-2xl p-2 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <span className="text-base font-semibold">Income</span>{' '}
                <span className="money mt-3 text-2xl font-bold tracking-tight">{money(monthly.income)}</span>
              </button>
              <Sparkline values={trend.map(value => Number(value.income))} color="hsl(var(--chart-2))" />
              {lastMonth && <p className="mt-1 text-sm font-medium text-info"><span className="money">{money(lastMonth.income)}</span> last month</p>}
              <p className="mt-auto pt-3 text-xs text-muted-foreground">12-month trend. Select the amount for this month’s income transactions.</p>
            </SectionCard>

            <SectionCard aria-label="Net Savings" className="flex min-w-0 flex-col p-4 sm:p-5">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-base font-semibold">Net Savings</h2>
                <span className={cn('inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-[0.04em]', netSavings >= 0 ? 'bg-success/15 text-success' : 'bg-destructive/15 text-destructive')}>
                  {netSavings >= 0 ? <ArrowUpRight aria-hidden="true" className="size-3.5" /> : <ArrowDownRight aria-hidden="true" className="size-3.5" />}
                  {netSavings >= 0 ? 'Saved' : 'Overspent'}
                </span>
              </div>
              <p className={cn('money mt-3 text-2xl font-bold tracking-tight', netSavings >= 0 ? 'text-success' : 'text-destructive')}>{signedDisplay(money(monthly.net_savings))}</p>
              <Sparkline values={trend.map(value => Number(value.net_savings))} color="hsl(var(--chart-1))" />
              {lastMonth && <p className="mt-1 text-sm font-medium text-info"><span className="money">{signedDisplay(money(lastMonth.net_savings))}</span> last month</p>}
              <p className="mt-auto pt-3 text-xs text-muted-foreground">12-month trend. Income − Net Spending.</p>
            </SectionCard>
          </div>

          <div className="mt-4 grid items-start gap-4 lg:grid-cols-2">
            <SpendingCategoryView categories={monthly.category_net_breakdown || []} metric={categoryMode}
              selectedCategory={detailFilter?.canonicalCategory} selectedComponent={detailFilter?.spendingComponent}
              onSelect={(category, component) => setDetailFilter(current => current?.canonicalCategory === category && current.spendingComponent === component
                ? null : { canonicalCategory: category, spendingComponent: component })}
              money={money} detailsId="overview-transaction-details" />

          <SectionCard className="min-w-0">
            <SectionHeader title={categoryMode === 'card_benefits' ? `Card Benefits by ${groupBy}`
              : categoryMode === 'reimbursements' ? `Reimbursements by ${groupBy}` : `Spending by ${groupBy}`}
              description={`Select a category above to filter these summaries by ${groupBy}.`}
              actions={<select aria-label="Group summary by" className={fieldClassName} value={groupBy} onChange={(event) => setGroupBy(event.target.value as 'institution' | 'account')}>
                <option value="institution">Institution</option><option value="account">Account</option>
              </select>} />
            <div className="flex flex-col px-1.5 pb-2">
              {breakdown.map((group) => (
                <button
                  type="button"
                  key={group.account_id || group.institution_id}
                  disabled={!detailFilter?.category && !detailFilter?.benefitCategory && !detailFilter?.canonicalCategory}
                  onClick={() => selectSecondary(group)}
                  aria-pressed={Boolean(detailFilter?.secondary && (group.account_id
                    ? detailFilter.secondary.account_id === group.account_id
                    : detailFilter.secondary.institution_id === group.institution_id))}
                  className={cn('flex min-w-0 items-center justify-between gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors enabled:hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                    detailFilter?.secondary && (group.account_id
                      ? detailFilter.secondary.account_id === group.account_id
                      : detailFilter.secondary.institution_id === group.institution_id) && 'bg-primary/15 ring-1 ring-inset ring-info/60')}
                >
                  <span className="flex min-w-0 flex-1 flex-col items-start">
                    {group.account_name ? (
                      <AccountBadge institutionName={group.institution_name} accountName={group.account_name} accountMask={group.account_mask || null} accountType={group.account_type || ''} accountSubtype={group.account_subtype} />
                    ) : <InstitutionBadge institutionName={group.institution_name} />}
                    {group.account_name && <span className="mt-1 block truncate text-xs text-muted-foreground">{group.institution_name}</span>}
                  </span>
                  <span className="shrink-0 text-right">
                    <span className="money block text-[15px] font-semibold">{money(categoryMode === 'card_benefits' ? group.benefit_amount || group.card_benefits
                      : categoryMode === 'reimbursements' ? group.reimbursements : group.net_spending)}</span>
                    <span className="block text-xs text-muted-foreground">{categoryMode === 'card_benefits' ? 'card benefits'
                      : categoryMode === 'reimbursements' ? 'reimbursements' : 'net spending'}</span>
                  </span>
                </button>
              ))}
              {breakdown.length === 0 && <p className="px-2.5 py-2.5 text-sm text-muted-foreground">No accounts contribute to this view.</p>}
            </div>
          </SectionCard>
          </div>

          {detailFilter && (
            <div id="overview-transaction-details" ref={detailSection} tabIndex={-1} className="mt-4 scroll-mt-20 focus:outline-none">
            <SectionCard>
              <div className="flex items-start justify-between gap-4 px-4 pb-4 pt-4 sm:px-5 sm:pt-5">
                <div className="min-w-0">
                  <h2 className="text-base font-semibold leading-6">Transaction Details</h2>
                  <div aria-label="Active detail filters" className="mt-2 flex flex-wrap items-center gap-1.5 text-sm">
                    <Badge variant="secondary" className="tabular-nums">{month}</Badge>
                    {detailFilter.label && <Badge variant="secondary">{labelOptions.options.find(option => option.value === detailFilter.label)?.label || detailFilter.label}</Badge>}
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
                      <button type="button" className="rounded-full bg-info/15 px-2.5 py-1 text-xs font-semibold text-info hover:bg-info/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => setDetailFilter({ ...detailFilter, secondary: undefined })}>
                        {detailFilter.secondary.institution_name}
                        {detailFilter.secondary.account_name ? ` · ${detailFilter.secondary.account_name} · ${detailFilter.secondary.account_mask || ''}` : ''}
                        {' · Clear ×'}
                      </button>
                    )}
                  </div>
                  <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
                    <p className="text-sm text-muted-foreground">{detailTotal} matching transactions</p>
                    {detailFilter.transactionType === 'reimbursement' &&
                      <p className="money text-sm font-semibold">Total reimbursements: {money(detailReimbursements)}</p>}
                    {detailFilter.label && <p className="money text-sm font-semibold">Net spending: {money(detailComponentTotals.net_spending || '0.00')}</p>}
                    {detailFilter.spendingComponent && <p className="money text-sm font-semibold">
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
              {detailLoading && <p role="status" className="px-4 py-3.5 text-sm text-muted-foreground sm:px-5">Loading transaction details…</p>}
              {!detailLoading && details.length === 0 && !error && <p className="px-4 py-3.5 text-sm text-muted-foreground sm:px-5">No matching transactions.</p>}
              <div className="px-1.5 pb-2">
                {groupByDay(details, detail => detail.transaction_date).map(group => <DayGroup key={group.date} date={group.date}>
                {group.rows.map((detail) => (
                  <TransactionRow key={detail.transaction_id}
                    select={<label>
                      <input type="checkbox" checked={selectedDetails.has(detail.transaction_id)}
                        disabled={bulkBusy} onChange={() => toggleDetail(detail.transaction_id)}
                        aria-label={`Select ${detail.merchant_name || detail.description || 'transaction'}`} />
                    </label>}
                    title={<p className="break-words font-medium">{detail.merchant_name || detail.description || 'Unknown transaction'}</p>}
                    meta={<>{detail.description} · <span className="capitalize">{detail.transaction_type.replace(/_/g, ' ')}</span></>}
                    pill={<CategoryEditor detail={detail} options={categoryOptions} busy={categoryBusy || bulkBusy} save={saveCategory} />}
                    amount={<>
                      <Amount value={detail.amount}>{money(detail.amount)}</Amount>
                      {detailFilter.spendingComponent === 'net' && detail.net_contribution && <p className="money text-xs font-medium text-muted-foreground">Net contribution {money(detail.net_contribution)}</p>}
                    </>}>
                    <ChipRow>
                      <MoreTags count={detail.institution_name && detail.account_name ? 1 : 0}>
                        {detail.institution_name && detail.account_name && (
                          <AccountBadge institutionName={detail.institution_name} accountName={detail.account_name} accountMask={detail.account_mask} accountType={detail.account_type || ''} accountSubtype={detail.account_subtype} />
                        )}
                      </MoreTags>
                      <BenefitCategoryEditor detail={detail} options={benefitCategoryOptions} disabled={bulkBusy} onChanged={changed => updateBenefitCategory(detail, changed)} />
                      <LabelEditor detail={detail} options={labelOptions.options}
                        optionsLoading={labelOptions.loading} optionsError={labelOptions.error}
                        disabled={bulkBusy} onRetryOptions={labelOptions.retry} onChanged={updateLabels} />
                    </ChipRow>
                  </TransactionRow>
                ))}
                </DayGroup>)}
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
              {detailTotal > detailPageSize && <Pagination className="border-t px-4 py-3 sm:px-5" offset={detailOffset} pageSize={detailPageSize} total={detailTotal} onPage={setDetailOffset} />}
            </SectionCard>
            </div>
          )}
        </>
      )}

      <SectionCard aria-labelledby="connected-institutions" className="mt-4">
        <SectionHeader id="connected-institutions" title="Connected Institutions" className="pb-2" />
        <div className="px-4 pb-4 sm:px-5"><PlaidLinkButton /></div>
      </SectionCard>
    </main>
    </>
  )
}
