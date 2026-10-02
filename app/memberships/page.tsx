'use client'

import { Amount, ChartLegend, ChartMonthlyTotals, ChipRow, ControlField, LoadingState, MoreTags, PageHeader, PageNavigation, Pagination, SectionCard, SectionHeader, SelectAllBar, StatButton, TransactionRow, TransactionTools, TransactionTypeBadge, cardClassName, chartAxisTick, compactMoney, fieldClassName, pageClassName, useNarrowViewport, useTransactionPageSize } from '@/components/page-presentation'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ChevronRight, CircleAlert, CircleCheck, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import AccountBadge from '@/components/account-badge'
import BulkTransactionEditor, { bulkErrorMessage, type BulkEditRequest } from '@/components/bulk-transaction-editor'
import CategoryEditor, { mergeCategoryDetail, mutateCategoryOverride, type CategoryDetail, type CategoryOption } from '@/components/category-editor'
import BenefitCategoryEditor, { type BenefitCategoryDetail, type BenefitCategoryOption } from '@/components/benefit-category-editor'
import LabelEditor, { mergeLabelDetail, type LabelDetail, useLabelOptions } from '@/components/label-editor'
import { SyncHealth, consistentJson, useSyncRefresh } from '@/components/sync-health'
import { membershipPeriods, membershipRangeText, membershipSummaryMatches,
  membershipSummaryPath, membershipTransactionsPath, type MembershipPeriod } from './period'
import type { MembershipView } from './period'

type MembershipMetrics = {
  gross_charges: string
  refunds: string
  reimbursements: string
  unallocated_reimbursements: string
  card_benefits: string
  net_cost: string
  reimbursement_transaction_count: number
  unallocated_reimbursement_transaction_count: number
  membership_transaction_count: number
  excluded_transaction_count: number
  unclassified_count: number
}
type MembershipAccount = MembershipMetrics & {
  institution_id: string
  institution_name: string
  account_id: string
  account_name: string
  account_mask: string | null
  account_type: string
  account_subtype: string | null
}
type MembershipSummary = {
  period: MembershipPeriod
  start_month: string
  end_month: string
  overall: MembershipMetrics
  months: Array<MembershipMetrics & { month: string }>
  accounts: MembershipAccount[]
  type_counts: { charges: number; refunds: number; reimbursements: number; card_benefits: number; excluded: number }
}
type Detail = CategoryDetail & BenefitCategoryDetail & LabelDetail & {
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
  is_spending: boolean | null
  is_internal_transfer: boolean | null
}


function currentMonth() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function money(value: string) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value))
}

function signedMoney(value: string) {
  const amount = Number(value)
  return (amount > 0 ? '+' : '') + money(value)
}

function contributesToCost(detail: Detail) {
  const amount = Number(detail.amount)
  if (detail.is_internal_transfer) return false
  return (detail.transaction_type === 'expense' && detail.is_spending === true && amount < 0)
    || ((detail.transaction_type === 'refund' || detail.transaction_type === 'card_benefit'
      || detail.transaction_type === 'reimbursement') && amount > 0)
}

function isMembershipReimbursement(detail: Detail) {
  return detail.transaction_type === 'reimbursement' && !detail.is_internal_transfer && Number(detail.amount) > 0
}

export default function MembershipsPage() {
  const [endMonth, setEndMonth] = useState(currentMonth)
  const [period, setPeriod] = useState<MembershipPeriod>('trailing_12m')
  const [summary, setSummary] = useState<MembershipSummary | null>(null)
  const [accountId, setAccountId] = useState<string | null>(null)
  const [view, setView] = useState<MembershipView>('all')
  const [details, setDetails] = useState<Detail[]>([])
  const [total, setTotal] = useState(0)
  const [viewCounts, setViewCounts] = useState({ charges: 0, refunds: 0, reimbursements: 0, card_benefits: 0, all: 0 })
  const [detailUnallocatedAmount, setDetailUnallocatedAmount] = useState('0.00')
  const [detailUnallocatedCount, setDetailUnallocatedCount] = useState(0)
  const pageSize = useTransactionPageSize()
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [optionsRetry, setOptionsRetry] = useState(0)
  const [status, setStatus] = useState('')
  const [categoryOptions, setCategoryOptions] = useState<CategoryOption[]>([])
  const [benefitCategoryOptions, setBenefitCategoryOptions] = useState<BenefitCategoryOption[]>([])
  const narrowViewport = useNarrowViewport()
  const labelOptions = useLabelOptions()
  const sync = useSyncRefresh()

  useEffect(() => {
    let active = true
    fetch('/api/pft/review/categories')
      .then(response => response.ok ? response.json() : Promise.reject())
      .then(data => { if (active) setCategoryOptions(data.categories || []) })
      .catch(() => { if (active) setError('Category options could not be loaded.') })
    fetch('/api/pft/review/benefit-categories')
      .then(response => response.ok ? response.json() : Promise.reject())
      .then(data => { if (active) setBenefitCategoryOptions(data.categories || []) })
      .catch(() => { if (active) setError('Benefit category options could not be loaded.') })
    return () => { active = false }
  }, [optionsRetry])

  useEffect(() => {
    let active = true
    setLoading(true)
    consistentJson([membershipSummaryPath(endMonth, period)], sync.check)
      .then(([data]) => { if (active) setSummary(data) })
      .catch(() => { if (active) setError('Membership costs could not be loaded.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [endMonth, period, revision, sync.revision, sync.check])

  useEffect(() => { setSelected(new Set()) }, [pageSize])

  const startMonth = summary && membershipSummaryMatches(summary, endMonth, period)
    ? summary.start_month : null
  useEffect(() => {
    if (!startMonth) return
    let active = true
    setDetailLoading(true)
    consistentJson([membershipTransactionsPath(startMonth, endMonth, accountId, offset, pageSize, view)], sync.check)
      .then(([data]) => {
        if (!active) return
        if (offset > 0 && offset >= data.total) {
          setOffset(Math.max(0, Math.floor((data.total - 1) / pageSize) * pageSize))
          return
        }
        setDetails(data.transactions || [])
        setSelected(new Set())
        setTotal(data.total || 0)
        setDetailUnallocatedAmount(data.unallocated_reimbursements || '0.00')
        setDetailUnallocatedCount(data.unallocated_reimbursement_transaction_count || 0)
        if (data.membership_counts) setViewCounts(data.membership_counts)
      })
      .catch(() => { if (active) setError('Membership transactions could not be loaded.') })
      .finally(() => { if (active) setDetailLoading(false) })
    return () => { active = false }
  }, [startMonth, endMonth, accountId, offset, pageSize, view, revision, sync.revision, sync.check])

  const selectedAccount = summary?.accounts.find(account => account.account_id === accountId)
  const chartData = useMemo(() => (summary?.months || []).map(month => ({
    month: month.month,
    netCost: Number(month.net_cost),
    grossCharges: Number(month.gross_charges),
    refunds: Number(month.refunds),
    reimbursements: Number(month.reimbursements),
    cardBenefits: Number(month.card_benefits),
  })), [summary])

  function resetDetails() {
    setOffset(0)
    setSelected(new Set())
    setDetails([])
    setTotal(0)
    setViewCounts({ charges: 0, refunds: 0, reimbursements: 0, card_benefits: 0, all: 0 })
    setDetailUnallocatedAmount('0.00')
    setDetailUnallocatedCount(0)
    setStatus('')
  }

  function changeAccount(nextId: string | null) {
    if (nextId === accountId) return
    setAccountId(nextId)
    resetDetails()
  }

  function changeView(nextView: MembershipView) {
    if (nextView === view) return
    setView(nextView)
    resetDetails()
  }

  function changePeriod(nextPeriod: MembershipPeriod) {
    if (nextPeriod === period) return
    setPeriod(nextPeriod)
    setSummary(null)
    setError('')
    setAccountId(null)
    resetDetails()
  }

  function toggleSelected(id: string) {
    setSelected(current => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const refresh = useCallback(() => {
    setSelected(new Set())
    setRevision(value => value + 1)
  }, [])

  async function saveCategory(detail: CategoryDetail, category: string | null) {
    setBusy(true)
    setError('')
    try {
      const changed = await mutateCategoryOverride(detail.transaction_id, category)
      setDetails(current => current.map(value => mergeCategoryDetail(value, changed)))
      setSelected(new Set())
      refresh()
      return true
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Category could not be saved.')
      return false
    } finally { setBusy(false) }
  }

  function updateLabels(changed: LabelDetail) {
    setDetails(current => current.map(value => mergeLabelDetail(value, changed)))
    refresh()
  }

  function updateBenefitCategory(changed: BenefitCategoryDetail) {
    setDetails(current => current.map(value => value.transaction_id === changed.transaction_id
      ? { ...value, ...changed } : value))
    refresh()
  }

  async function applyBulk(request: BulkEditRequest) {
    setBusy(true)
    setError('')
    setStatus('')
    try {
      const response = await fetch('/api/pft/review/transactions/bulk-edit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) throw new Error(bulkErrorMessage(data))
      setStatus(`${data.changed_count} changed · ${data.unchanged_count} already set.`)
      refresh()
      return true
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Bulk change could not be saved.')
      return false
    } finally { setBusy(false) }
  }

  const selectedDetails = details.filter(detail => selected.has(detail.transaction_id))
  const classificationOptions = [
    { value: 'reimbursement' as const, label: 'Reimbursement', eligibleCount: selectedDetails.filter(detail => Number(detail.amount) > 0 && detail.is_internal_transfer !== true).length },
    { value: 'expense' as const, label: 'Expense', eligibleCount: selectedDetails.filter(detail => Number(detail.amount) < 0 && detail.is_internal_transfer !== true).length },
  ]

  const lineColor = { netCost: 'hsl(var(--chart-1))', grossCharges: 'hsl(var(--muted-foreground))', refunds: 'hsl(var(--chart-2))', reimbursements: 'hsl(185 70% 55%)', cardBenefits: 'hsl(var(--chart-4))' }
  // Composition of gross charges: what remains as net cost and what each credit type took off it.
  const composition = summary ? ([
    ['Net cost', summary.overall.net_cost, lineColor.netCost],
    ['Refunds', summary.overall.refunds, lineColor.refunds],
    ['Reimbursements', summary.overall.reimbursements, lineColor.reimbursements],
    ['Card benefits', summary.overall.card_benefits, lineColor.cardBenefits],
  ] as const).map(([label, value, color]) => ({ label, value: Number(value), color })) : []
  const compositionTotal = composition.reduce((sum, part) => sum + part.value, 0)
  // A part-to-whole bar cannot represent a net credit as a positive cost share.
  const showComposition = compositionTotal > 0 && composition.every(part => part.value >= 0)
  return <>
  <PageNavigation current="Memberships" />
  <main className={pageClassName}>
    <PageHeader title="Membership costs" description="Membership charges and credits across active accounts."
      meta={summary && <p className="mt-1 text-sm tabular-nums text-muted-foreground">
        {membershipRangeText(summary.start_month, summary.end_month, period)}
        {endMonth === currentMonth() ? ' · current month is partial' : ''}
      </p>}
      actions={<>
        <ControlField label="Period" className="min-w-[11rem]">
          <select value={period} className={fieldClassName}
            onChange={event => changePeriod(event.target.value as MembershipPeriod)}>
            {membershipPeriods.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </ControlField>
        <ControlField label="Ending month" className="min-w-[11rem]">
          <input type="month" value={endMonth} max={currentMonth()} className={fieldClassName}
            onChange={event => {
              if (!event.target.value || event.target.value === endMonth) return
              setEndMonth(event.target.value)
              setSummary(null)
              setError('')
              setAccountId(null)
              resetDetails()
            }} />
        </ControlField>
      </>} />
    <div className="mt-5"><SyncHealth status={sync.status} error={sync.error} onRetry={() => { void sync.check().catch(() => undefined) }} /></div>
    {error && <Alert role="alert" variant="destructive" className="mt-4"><CircleAlert aria-hidden="true" /><span className="min-w-0 flex-1">{error}</span> <Button type="button" variant="outline" size="sm" onClick={() => { setError(''); setOptionsRetry(value => value + 1); sync.invalidate() }}>Retry loading</Button></Alert>}
    {status && <Alert role="status" variant="success" className="mt-4"><CircleCheck aria-hidden="true" />{status}</Alert>}
    {loading && !summary && <LoadingState label="Loading membership costs…" rows={3} />}
    {summary && <>
      <div className="mt-6 grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
      <div className={cn(cardClassName, 'min-w-0')}>
        <SectionHeader title="Net membership cost" />
        <section aria-label="Overall membership costs" className="px-2 sm:px-3">
          <div className="flex flex-col items-center text-center">
            <button type="button" aria-pressed={!accountId && view === 'all'} onClick={() => { changeAccount(null); changeView('all') }}
              className={cn('flex max-w-full flex-col items-center rounded-2xl px-4 py-1.5 transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', !accountId && view === 'all' && 'bg-primary/10')}>
              <span className="order-2 text-sm font-semibold text-muted-foreground">Net cost</span>{' '}
              <span className="money order-1 text-[26px] font-bold leading-tight tracking-tight min-[380px]:text-[30px] sm:text-[34px]">{money(summary.overall.net_cost)}</span>
            </button>
          </div>
          {showComposition && <div data-membership-composition aria-hidden="true" className="mx-2 mt-4 flex h-2.5 gap-0.5 overflow-hidden rounded-full sm:mx-1">
            {composition.filter(part => part.value > 0).map(part => <span key={part.label} className="h-full rounded-full"
              style={{ width: `${part.value / compositionTotal * 100}%`, minWidth: 4, background: part.color }} />)}
          </div>}
          <div className="mt-3 grid grid-cols-1 gap-1 min-[380px]:grid-cols-2">
            {([
              ['Gross charges', summary.overall.gross_charges, 'charges', undefined, undefined],
              ['Refunds', summary.overall.refunds, 'refunds', '−', lineColor.refunds],
              ['Reimbursements', summary.overall.reimbursements, 'reimbursements', '−', lineColor.reimbursements],
              ['Card benefits', summary.overall.card_benefits, 'card_benefits', '−', lineColor.cardBenefits],
            ] as const).map(([name, value, targetView, operator, color]) => <StatButton key={name} label={name} value={money(value)} operator={operator} color={color}
              selected={!accountId && view === targetView} onClick={() => { changeAccount(null); changeView(targetView) }} />)}
          </div>
        </section>
        <div className="flex flex-col gap-2 px-4 pb-4 pt-3 text-sm sm:px-5 sm:pb-5">
          <details className="group rounded-xl bg-muted/60 px-3 py-2.5">
            <summary className="flex cursor-pointer list-none items-start gap-1.5 rounded-md font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
              <ChevronRight aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
              How net cost is calculated
            </summary>
            <div className="mt-2 pl-[22px] text-[13px] leading-5 text-muted-foreground">
              <p>Net Membership Cost = gross charges − refunds − reimbursements − card benefits. Each transaction affects its posted month.</p>
              <p className="mt-1">
                {summary.type_counts.charges} charges · {summary.type_counts.refunds} refunds · {summary.type_counts.reimbursements} reimbursements · {summary.type_counts.card_benefits} card benefit credits · {summary.overall.excluded_transaction_count} excluded from cost
                {summary.overall.unclassified_count > 0 ? ` (${summary.overall.unclassified_count} unclassified)` : ''}.
                {' '}Payments, transfers, adjustments, income, and unclassified entries do not affect cost.
              </p>
            </div>
          </details>
          <details aria-label="Membership reconciliation" className="group rounded-xl bg-muted/60 px-3 py-2.5">
            <summary className="flex cursor-pointer list-none items-start gap-1.5 rounded-md font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
              <ChevronRight aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
              <span className="money min-w-0 whitespace-normal">Unallocated reimbursements: {money(summary.overall.unallocated_reimbursements)} · {summary.overall.unallocated_reimbursement_transaction_count} transactions</span>
            </summary>
            <div className="mt-2 pl-[22px] text-[13px] leading-5">
              <p className="text-muted-foreground">These reduce overall Membership net cost, but do not reduce any individual account’s net cost. Receiving accounts identify where the money arrived, not which membership expense it repays.</p>
              <p className="mt-2">Sum of per-account net costs − unallocated reimbursements = overall net cost.</p>
              <p className="money whitespace-normal text-muted-foreground">Unallocated deduction: {money(summary.overall.unallocated_reimbursements)} · Overall net cost: {money(summary.overall.net_cost)}</p>
            </div>
          </details>
        </div>
      </div>

      <SectionCard className="min-w-0">
        <SectionHeader title="Monthly membership cost" description="By posted month, in US dollars" />
        <div className="px-4 pb-4 sm:px-5 sm:pb-5">
          <ChartLegend items={[{ label: 'Net cost', color: lineColor.netCost }, { label: 'Gross charges', color: lineColor.grossCharges },
            { label: 'Refunds', color: lineColor.refunds }, { label: 'Reimbursements', color: lineColor.reimbursements, dashed: true }, { label: 'Card benefits', color: lineColor.cardBenefits }]} />
          <div className="mt-3 h-64 min-w-0 sm:h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart accessibilityLayer data={chartData} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 5" />
                <XAxis dataKey="month" tickLine={false} axisLine={false} tick={chartAxisTick} minTickGap={narrowViewport ? 40 : 18} tickFormatter={value => value.slice(5)} />
                <YAxis tickCount={narrowViewport ? 4 : 5} width={56} tickLine={false} axisLine={false} tick={chartAxisTick} tickFormatter={compactMoney} />
                <Tooltip trigger={narrowViewport ? 'click' : 'hover'} position={narrowViewport ? { x: 4, y: 4 } : undefined} wrapperStyle={{ maxWidth: 'calc(100% - 8px)' }} content={({ active, payload }) => {
                  const month = payload?.[0]?.payload as typeof chartData[number] | undefined
                  return active && month ? <div className="max-w-full rounded-xl border bg-popover p-3 text-[13px] tabular-nums text-popover-foreground shadow-[0_12px_32px_rgb(0_0_0/0.45)] [overflow-wrap:anywhere]">
                    <p className="font-semibold">{month.month}</p>
                    <p>Gross charges: {money(String(month.grossCharges))}</p>
                    <p>Refunds: {money(String(month.refunds))}</p>
                    <p>Reimbursements: {money(String(month.reimbursements))}</p>
                    <p>Card benefits: {money(String(month.cardBenefits))}</p>
                    <p className="mt-1 border-t pt-1 font-semibold">Net cost: {money(String(month.netCost))}</p>
                  </div> : null
                }} />
                <Line isAnimationActive={false} type="monotone" dataKey="grossCharges" name="Gross charges" stroke={lineColor.grossCharges} strokeWidth={1.5} dot={false} />
                <Line isAnimationActive={false} type="monotone" dataKey="refunds" name="Refunds" stroke={lineColor.refunds} strokeWidth={1.5} dot={false} />
                <Line isAnimationActive={false} type="monotone" dataKey="reimbursements" name="Reimbursements" stroke={lineColor.reimbursements} strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
                <Line isAnimationActive={false} type="monotone" dataKey="cardBenefits" name="Card benefits" stroke={lineColor.cardBenefits} strokeWidth={1.5} dot={false} />
                <Line isAnimationActive={false} type="monotone" dataKey="netCost" name="Net cost" stroke={lineColor.netCost} strokeWidth={3} strokeLinecap="round" dot={false} activeDot={{ r: 5 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <ChartMonthlyTotals rows={chartData} columns={[{ key: 'netCost', label: 'Net cost' }, { key: 'grossCharges', label: 'Gross charges' }, { key: 'refunds', label: 'Refunds' }, { key: 'reimbursements', label: 'Reimbursements' }, { key: 'cardBenefits', label: 'Card benefits' }]} money={money} />
        </div>
      </SectionCard>
      </div>

      <section className="mt-8" aria-labelledby="membership-accounts">
        <h2 id="membership-accounts" className="text-xs font-bold uppercase tracking-[0.08em] text-info">By account</h2>
        <p className="mt-1 text-[13px] text-muted-foreground">Account net costs exclude unallocated reimbursements. Reimbursements received are shown only as source context.</p>
        {summary.accounts.length === 0 && <p className="mt-3 text-sm text-muted-foreground">No Membership transactions in this period.</p>}
        <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {summary.accounts.map(account => <div key={account.account_id}
            className={cn(cardClassName, 'flex min-w-0 flex-col overflow-hidden text-left', accountId === account.account_id && 'border-info/70 ring-1 ring-info/70')}>
            <button type="button" aria-pressed={accountId === account.account_id}
              className="flex w-full min-w-0 flex-col items-start p-4 text-left transition-colors hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:px-5"
              onClick={() => { changeAccount(accountId === account.account_id ? null : account.account_id); changeView('all') }}>
              <AccountBadge institutionName={account.institution_name} accountName={account.account_name}
                accountMask={account.account_mask} accountType={account.account_type} accountSubtype={account.account_subtype} />
              <p className="money mt-3 text-[22px] font-bold leading-tight tracking-tight">{money(account.net_cost)} net cost</p>
              <dl className="mt-3 grid w-full grid-cols-2 gap-x-4 gap-y-2 text-sm tabular-nums">
                <div className="min-w-0"><dt className="text-xs text-muted-foreground">Gross</dt><dd className="[overflow-wrap:anywhere]">{money(account.gross_charges)}</dd></div>
                <div className="min-w-0"><dt className="text-xs text-muted-foreground">Refunds</dt><dd className="[overflow-wrap:anywhere]">{money(account.refunds)}</dd></div>
                <div className="min-w-0"><dt className="text-xs text-muted-foreground">Benefits</dt><dd className="[overflow-wrap:anywhere]">{money(account.card_benefits)}</dd></div>
                <div className="min-w-0"><dt className="text-xs text-muted-foreground">Transactions</dt><dd>{account.membership_transaction_count} Membership transactions</dd></div>
              </dl>
            </button>
            <div className="mt-auto flex flex-col items-start gap-2 border-t px-4 py-3 sm:px-5">
              <Button type="button" variant="outline" size="sm"
                onClick={event => { event.stopPropagation(); changeAccount(account.account_id); changeView('card_benefits') }}>
                View {money(account.card_benefits)} benefits
              </Button>
              {account.unallocated_reimbursement_transaction_count > 0 && <div className="text-xs text-muted-foreground">
                <p>Unallocated reimbursements received: {money(account.unallocated_reimbursements)} · {account.unallocated_reimbursement_transaction_count} transactions</p>
                <Button type="button" variant="link" size="inline" className="mt-1 text-xs"
                  onClick={() => { changeAccount(account.account_id); changeView('reimbursements') }}>
                  View reimbursements received
                </Button>
              </div>}
              {account.excluded_transaction_count > 0 && <p className="text-xs text-muted-foreground">
                {account.excluded_transaction_count} excluded from cost
              </p>}
            </div>
          </div>)}
        </div>
      </section>

      <SectionCard className="mt-8">
        <SectionHeader title="Membership transactions"
          description={<>
            <p>
              {selectedAccount ? `${selectedAccount.institution_name} · ${selectedAccount.account_name}`
                : accountId ? 'Selected account (no matching costs)' : 'All accounts'}
              {' · '}{total} {view === 'all' ? 'Membership transactions' : view === 'card_benefits' ? 'card benefit credits' : view === 'charges' ? 'membership charges' : view === 'reimbursements' ? 'membership reimbursements' : 'membership refunds'} in the reporting period
            </p>
            {view === 'reimbursements' && !detailLoading && <p className="mt-2 font-medium text-foreground">
              Unallocated reimbursements in this filter: {money(detailUnallocatedAmount)} · {detailUnallocatedCount} transactions across all pages.
              <span className="block text-xs font-normal text-muted-foreground">Account filtering identifies the receiving account; these credits reduce overall cost only.</span>
            </p>}
          </>}
          actions={accountId && <Button type="button" variant="link" size="inline"
            onClick={() => changeAccount(null)}>Show all accounts</Button>} />
        <div className="px-4 pb-4 sm:px-5">
          <div className="inline-flex max-w-full flex-wrap gap-0.5 rounded-[18px] border bg-background/40 p-1" aria-label="Membership transaction type filter">
            {([['all', 'All'], ['charges', 'Charges'], ['refunds', 'Refunds'], ['reimbursements', 'Reimbursements'], ['card_benefits', 'Card Benefits']] as const).map(([value, label]) => (
              <Button key={value} type="button" size="sm" variant="ghost" aria-pressed={view === value}
                className={cn('text-muted-foreground hover:bg-accent', view === value && 'bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground')}
                onClick={() => changeView(value)}>{label}{summary && <span className="ml-1 tabular-nums opacity-75">({value === 'all' ? viewCounts.all : viewCounts[value]})</span>}</Button>
            ))}
          </div>
        </div>
        {detailLoading && <p className="border-t px-4 py-3.5 text-sm text-muted-foreground sm:px-5">Loading transactions…</p>}
        {!detailLoading && details.length > 0 && <SelectAllBar className="border-t">
          <label className="inline-flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={details.every(detail => selected.has(detail.transaction_id))}
              ref={element => { if (element) element.indeterminate = selected.size > 0 && !details.every(detail => selected.has(detail.transaction_id)) }}
              disabled={busy}
              onChange={event => setSelected(event.target.checked
                ? new Set(details.map(detail => detail.transaction_id)) : new Set())} />
            Select all displayed ({details.length})
          </label>
        </SelectAllBar>}
        {!detailLoading && details.length === 0 && <p className="border-t px-4 py-3.5 text-sm text-muted-foreground sm:px-5">No matching transactions.</p>}
        <div className="px-1.5 py-1 empty:hidden">
          {!detailLoading && details.map(detail => <TransactionRow as="article" key={detail.transaction_id}
            select={<label><input type="checkbox" checked={selected.has(detail.transaction_id)} disabled={busy}
              aria-label={`Select ${detail.merchant_name || detail.description || 'transaction'}`}
              onChange={() => toggleSelected(detail.transaction_id)} /></label>}
            title={<p className="font-medium break-words">{detail.merchant_name || detail.description || 'Unknown transaction'}</p>}
            date={detail.transaction_date}
            meta={<>
              {detail.merchant_name && detail.description !== detail.merchant_name && detail.description}
              {!contributesToCost(detail) && <Badge variant="warning" className="mt-1 flex w-fit"><TriangleAlert aria-hidden="true" className="size-3" />Excluded from cost</Badge>}
              {isMembershipReimbursement(detail) && <p className="mt-1 text-xs">Reduces overall cost only · receiving account shown as context</p>}
            </>}
            pill={<CategoryEditor detail={detail} options={categoryOptions} busy={busy} save={saveCategory} />}
            amount={<Amount value={detail.amount}>{signedMoney(detail.amount)}</Amount>}>
            <TransactionTools count={detail.institution_name && detail.account_name ? 2 : 1}>
              <ChipRow className="mt-0">
                <MoreTags count={detail.institution_name && detail.account_name ? 2 : 1}>
                  <TransactionTypeBadge type={detail.transaction_type} />
                  {detail.institution_name && detail.account_name && <AccountBadge institutionName={detail.institution_name} accountName={detail.account_name}
                    accountMask={detail.account_mask} accountType={detail.account_type || ''} accountSubtype={detail.account_subtype} />}
                </MoreTags>
                <BenefitCategoryEditor detail={detail} options={benefitCategoryOptions} disabled={busy} onChanged={updateBenefitCategory} />
                <LabelEditor detail={detail} options={labelOptions.options} optionsLoading={labelOptions.loading}
                  optionsError={labelOptions.error} onRetryOptions={labelOptions.retry} disabled={busy} onChanged={updateLabels} />
              </ChipRow>
            </TransactionTools>
          </TransactionRow>)}
        </div>
        {selected.size > 0 && <div className="min-w-0"><BulkTransactionEditor
          transactionIds={Array.from(selected)} categoryOptions={categoryOptions} labelOptions={labelOptions.options}
          benefitCategoryOptions={benefitCategoryOptions}
          categoryIneligibleCount={details.filter(detail => selected.has(detail.transaction_id) && !detail.category_editable).length}
          benefitIneligibleCount={selectedDetails.filter(detail => !detail.benefit_category_editable).length}
          allowClassification classificationOptions={classificationOptions}
          allowCategory allowBenefitCategory busy={busy} errorMessage={error} onApply={applyBulk} onClear={() => setSelected(new Set())} />
        </div>}
        <Pagination className="border-t px-4 py-3 sm:px-5" offset={offset} pageSize={pageSize} total={total}
          disabled={busy || detailLoading} onPage={next => { setOffset(next); setSelected(new Set()) }} />
      </SectionCard>
    </>}
  </main>
  </>
}
