'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import AccountBadge from '@/components/account-badge'
import BulkTransactionEditor, { bulkErrorMessage, type BulkEditRequest } from '@/components/bulk-transaction-editor'
import CategoryEditor, { mergeCategoryDetail, mutateCategoryOverride, type CategoryDetail, type CategoryOption } from '@/components/category-editor'
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
  is_spending: boolean | null
  is_internal_transfer: boolean | null
}

const PAGE_SIZE = 50

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
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [categoryOptions, setCategoryOptions] = useState<CategoryOption[]>([])
  const labelOptions = useLabelOptions()
  const sync = useSyncRefresh()

  useEffect(() => {
    let active = true
    fetch('/api/pft/review/categories')
      .then(response => response.ok ? response.json() : Promise.reject())
      .then(data => { if (active) setCategoryOptions(data.categories || []) })
      .catch(() => { if (active) setError('Category options could not be loaded.') })
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true)
    consistentJson([membershipSummaryPath(endMonth, period)], sync.check)
      .then(([data]) => { if (active) setSummary(data) })
      .catch(() => { if (active) setError('Membership costs could not be loaded.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [endMonth, period, revision, sync.revision, sync.check])

  const startMonth = summary && membershipSummaryMatches(summary, endMonth, period)
    ? summary.start_month : null
  useEffect(() => {
    if (!startMonth) return
    let active = true
    setDetailLoading(true)
    consistentJson([membershipTransactionsPath(startMonth, endMonth, accountId, offset, PAGE_SIZE, view)], sync.check)
      .then(([data]) => {
        if (!active) return
        if (offset > 0 && offset >= data.total) {
          setOffset(Math.max(0, Math.floor((data.total - 1) / PAGE_SIZE) * PAGE_SIZE))
          return
        }
        setDetails(data.transactions || [])
        setTotal(data.total || 0)
        setDetailUnallocatedAmount(data.unallocated_reimbursements || '0.00')
        setDetailUnallocatedCount(data.unallocated_reimbursement_transaction_count || 0)
        if (data.membership_counts) setViewCounts(data.membership_counts)
      })
      .catch(() => { if (active) setError('Membership transactions could not be loaded.') })
      .finally(() => { if (active) setDetailLoading(false) })
    return () => { active = false }
  }, [startMonth, endMonth, accountId, offset, view, revision, sync.revision, sync.check])

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

  return <main className="container mx-auto max-w-7xl px-4 py-8">
    <Link href="/" className="text-sm font-medium text-blue-700 underline">Back to overview</Link>
    <header className="mt-4 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-3xl font-bold">Membership costs</h1>
        <p className="mt-1 text-sm text-muted-foreground">Net Membership Cost = gross charges − refunds − reimbursements − card benefits. Each transaction affects its posted month.</p>
        {summary && <p className="mt-1 text-sm text-muted-foreground">
          {membershipRangeText(summary.start_month, summary.end_month, period)}
          {endMonth === currentMonth() ? ' · current month is partial' : ''}
        </p>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm font-medium">Period{' '}
          <select value={period} className="ml-2 rounded-md border bg-white px-3 py-2"
            onChange={event => changePeriod(event.target.value as MembershipPeriod)}>
            {membershipPeriods.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="text-sm font-medium">Ending month{' '}
          <input type="month" value={endMonth} max={currentMonth()}
            className="ml-2 rounded-md border bg-white px-3 py-2"
            onChange={event => {
              if (!event.target.value || event.target.value === endMonth) return
              setEndMonth(event.target.value)
              setSummary(null)
              setError('')
              setAccountId(null)
              resetDetails()
            }} />
        </label>
      </div>
    </header>
    <div className="mt-5"><SyncHealth status={sync.status} error={sync.error} /></div>
    {error && <p role="alert" className="mt-5 rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {status && <p role="status" className="mt-5 rounded-md border bg-slate-50 p-3 text-sm">{status}</p>}
    {loading && <p className="mt-6 text-sm text-muted-foreground">Loading membership costs…</p>}
    {summary && <>
      <section className="mt-7 grid gap-4 sm:grid-cols-2 lg:grid-cols-5" aria-label="Overall membership costs">
        {([
          ['Gross charges', summary.overall.gross_charges, 'charges'],
          ['Refunds', summary.overall.refunds, 'refunds'],
          ['Reimbursements', summary.overall.reimbursements, 'reimbursements'],
          ['Card benefits', summary.overall.card_benefits, 'card_benefits'],
          ['Net cost', summary.overall.net_cost, 'all'],
        ] as const).map(([name, value, targetView]) => <div key={name} className="rounded-lg border bg-white p-5 shadow-sm">
          <button type="button" className="w-full text-left hover:text-blue-800"
            onClick={() => { changeAccount(null); changeView(targetView) }}>
            <p className="text-sm text-muted-foreground">{name}</p>
            <p className="mt-1 text-2xl font-bold">{money(value)}</p>
            <span className="text-xs text-blue-700 underline">{targetView === 'all' ? 'View all transactions' : 'View transactions'}</span>
          </button>
        </div>)}
      </section>
      <p className="mt-3 text-xs text-muted-foreground">
        {summary.type_counts.charges} charges · {summary.type_counts.refunds} refunds · {summary.type_counts.reimbursements} reimbursements · {summary.type_counts.card_benefits} card benefit credits · {summary.overall.excluded_transaction_count} excluded from cost
        {summary.overall.unclassified_count > 0 ? ` (${summary.overall.unclassified_count} unclassified)` : ''}.
        {' '}Payments, transfers, adjustments, income, and unclassified entries do not affect cost.
      </p>
      <section aria-label="Membership reconciliation" className="mt-4 rounded-md border bg-slate-50 p-4 text-sm">
        <p className="font-semibold">Unallocated reimbursements: {money(summary.overall.unallocated_reimbursements)} · {summary.overall.unallocated_reimbursement_transaction_count} transactions</p>
        <p className="mt-1 text-muted-foreground">These reduce overall Membership net cost, but do not reduce any individual account’s net cost. Receiving accounts identify where the money arrived, not which membership expense it repays.</p>
        <p className="mt-2">Sum of per-account net costs − unallocated reimbursements = overall net cost.</p>
        <p className="text-muted-foreground">Unallocated deduction: {money(summary.overall.unallocated_reimbursements)} · Overall net cost: {money(summary.overall.net_cost)}</p>
      </section>

      <section className="mt-8 rounded-lg border bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold">Monthly membership cost</h2>
        <div className="mt-4 h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ left: 10, right: 12 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" tickFormatter={value => value.slice(5)} />
              <YAxis tickFormatter={value => `$${value}`} />
              <Legend />
              <Tooltip content={({ active, payload }) => {
                const month = payload?.[0]?.payload as typeof chartData[number] | undefined
                return active && month ? <div className="rounded-md border bg-white p-3 text-xs shadow">
                  <p className="font-semibold">{month.month}</p>
                  <p>Gross charges: {money(String(month.grossCharges))}</p>
                  <p>Refunds: {money(String(month.refunds))}</p>
                  <p>Reimbursements: {money(String(month.reimbursements))}</p>
                  <p>Card benefits: {money(String(month.cardBenefits))}</p>
                  <p className="font-semibold">Net cost: {money(String(month.netCost))}</p>
                </div> : null
              }} />
              <Line type="monotone" dataKey="grossCharges" name="Gross charges" stroke="#0f172a" />
              <Line type="monotone" dataKey="refunds" name="Refunds" stroke="#15803d" />
              <Line type="monotone" dataKey="reimbursements" name="Reimbursements" stroke="#a16207" strokeDasharray="4 3" />
              <Line type="monotone" dataKey="cardBenefits" name="Card benefits" stroke="#7e22ce" />
              <Line type="monotone" dataKey="netCost" name="Net cost" stroke="#2563eb" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-semibold">By account</h2>
        <p className="mt-1 text-sm text-muted-foreground">Account net costs exclude unallocated reimbursements. Reimbursements received are shown only as source context.</p>
        {summary.accounts.length === 0 && <p className="mt-3 text-sm text-muted-foreground">No Membership transactions in this period.</p>}
        <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {summary.accounts.map(account => <div key={account.account_id}
            className={`rounded-lg border bg-white p-4 text-left shadow-sm ${accountId === account.account_id ? 'border-blue-600 ring-2 ring-blue-200' : ''}`}>
            <button type="button" aria-pressed={accountId === account.account_id}
              className="w-full text-left hover:text-blue-800"
              onClick={() => { changeAccount(accountId === account.account_id ? null : account.account_id); changeView('all') }}>
            <AccountBadge institutionName={account.institution_name} accountName={account.account_name}
              accountMask={account.account_mask} accountType={account.account_type} accountSubtype={account.account_subtype} />
            <p className="mt-3 text-lg font-semibold">{money(account.net_cost)} net cost</p>
            <div className="mt-2 grid grid-cols-2 gap-x-3 text-sm text-muted-foreground">
              <span>Gross {money(account.gross_charges)}</span><span>Refunds {money(account.refunds)}</span>
              <span>Benefits {money(account.card_benefits)}</span>
              <span>{account.membership_transaction_count} Membership transactions</span>
            </div>
            </button>
            <button type="button" className="mt-3 inline-flex items-center rounded-md border px-2 py-1 text-xs font-medium"
              onClick={event => { event.stopPropagation(); changeAccount(account.account_id); changeView('card_benefits') }}>
              View {money(account.card_benefits)} benefits
            </button>
            {account.unallocated_reimbursement_transaction_count > 0 && <div className="mt-3 text-xs text-muted-foreground">
              <p>Unallocated reimbursements received: {money(account.unallocated_reimbursements)} · {account.unallocated_reimbursement_transaction_count} transactions</p>
              <button type="button" className="mt-1 text-blue-700 underline"
                onClick={() => { changeAccount(account.account_id); changeView('reimbursements') }}>
                View reimbursements received
              </button>
            </div>}
            {account.excluded_transaction_count > 0 && <p className="mt-2 text-xs text-muted-foreground">
              {account.excluded_transaction_count} excluded from cost
            </p>}
          </div>)}
        </div>
      </section>

      <section className="mt-8 overflow-hidden rounded-lg border bg-white shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3 p-5">
          <div>
            <h2 className="text-lg font-semibold">Membership transactions</h2>
            <p className="text-sm text-muted-foreground">
              {selectedAccount ? `${selectedAccount.institution_name} · ${selectedAccount.account_name}`
                : accountId ? 'Selected account (no matching costs)' : 'All accounts'}
              {' · '}{total} {view === 'all' ? 'Membership transactions' : view === 'card_benefits' ? 'card benefit credits' : view === 'charges' ? 'membership charges' : view === 'reimbursements' ? 'membership reimbursements' : 'membership refunds'} in the reporting period
            </p>
            {view === 'reimbursements' && !detailLoading && <p className="mt-2 text-sm font-medium">
              Unallocated reimbursements in this filter: {money(detailUnallocatedAmount)} · {detailUnallocatedCount} transactions across all pages.
              <span className="block text-xs font-normal text-muted-foreground">Account filtering identifies the receiving account; these credits reduce overall cost only.</span>
            </p>}
          </div>
          <div className="flex flex-wrap gap-2" aria-label="Membership transaction type filter">
            {([['all', 'All'], ['charges', 'Charges'], ['refunds', 'Refunds'], ['reimbursements', 'Reimbursements'], ['card_benefits', 'Card Benefits']] as const).map(([value, label]) => (
              <button key={value} type="button" aria-pressed={view === value}
                className={`rounded-md border px-2 py-1 text-xs ${view === value ? 'border-blue-600 bg-blue-50 text-blue-800' : 'bg-white'}`}
                onClick={() => changeView(value)}>{label}{summary && <span className="ml-1">({value === 'all' ? viewCounts.all : viewCounts[value]})</span>}</button>
            ))}
          </div>
          {accountId && <button type="button" className="text-sm text-blue-700 underline"
            onClick={() => changeAccount(null)}>Show all accounts</button>}
        </div>
        {detailLoading && <p className="border-t p-4 text-sm text-muted-foreground">Loading transactions…</p>}
        {!detailLoading && details.length > 0 && <div className="border-t bg-slate-50 px-4 py-3">
          <label className="inline-flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={details.every(detail => selected.has(detail.transaction_id))}
              ref={element => { if (element) element.indeterminate = selected.size > 0 && !details.every(detail => selected.has(detail.transaction_id)) }}
              disabled={busy}
              onChange={event => setSelected(event.target.checked
                ? new Set(details.map(detail => detail.transaction_id)) : new Set())} />
            Select all displayed ({details.length})
          </label>
        </div>}
        {!detailLoading && details.length === 0 && <p className="border-t p-5 text-sm text-muted-foreground">No matching transactions.</p>}
        <div className="divide-y">
          {!detailLoading && details.map(detail => <article key={detail.transaction_id} className="flex flex-wrap items-start gap-3 p-4">
            <label className="pt-1"><input type="checkbox" checked={selected.has(detail.transaction_id)} disabled={busy}
              aria-label={`Select ${detail.merchant_name || detail.description || 'transaction'}`}
              onChange={() => toggleSelected(detail.transaction_id)} /></label>
            <div className="min-w-0 flex-1">
              <p className="font-medium">{detail.merchant_name || detail.description || 'Unknown transaction'}</p>
              <p className="text-sm text-muted-foreground">{detail.transaction_date} · {detail.description}</p>
              <span className="mt-1 inline-flex rounded-full border px-2 py-0.5 text-xs font-medium capitalize">
                {detail.transaction_type.replace(/_/g, ' ')}
              </span>
              {detail.institution_name && detail.account_name && <div className="mt-2">
                <AccountBadge institutionName={detail.institution_name} accountName={detail.account_name}
                  accountMask={detail.account_mask} accountType={detail.account_type || ''} accountSubtype={detail.account_subtype} />
              </div>}
            </div>
            <div className="text-right">
              <p className="font-semibold">{signedMoney(detail.amount)}</p>
              {isMembershipReimbursement(detail) && <p className="text-xs text-muted-foreground">Reduces overall cost only · receiving account shown as context</p>}
              {!contributesToCost(detail) && <p className="text-xs text-amber-800">Excluded from cost</p>}
            </div>
            <div className="grid w-full gap-x-5 md:grid-cols-2">
              <CategoryEditor detail={detail} options={categoryOptions} busy={busy} save={saveCategory} />
              <LabelEditor detail={detail} options={labelOptions.options} optionsLoading={labelOptions.loading}
                optionsError={labelOptions.error} onRetryOptions={labelOptions.retry} disabled={busy} onChanged={updateLabels} />
            </div>
          </article>)}
        </div>
        {selected.size > 0 && <div className="p-4"><BulkTransactionEditor
          transactionIds={Array.from(selected)} categoryOptions={categoryOptions} labelOptions={labelOptions.options}
          categoryIneligibleCount={details.filter(detail => selected.has(detail.transaction_id) && !detail.category_editable).length}
          allowCategory busy={busy} onApply={applyBulk} onClear={() => setSelected(new Set())} />
        </div>}
        <div className="flex items-center gap-4 border-t p-5 text-sm">
          <button type="button" disabled={busy || detailLoading || offset === 0} className="text-blue-700 underline disabled:opacity-40"
            onClick={() => { setOffset(Math.max(0, offset - PAGE_SIZE)); setSelected(new Set()) }}>Previous</button>
          <span>{total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span>
          <button type="button" disabled={busy || detailLoading || offset + PAGE_SIZE >= total} className="text-blue-700 underline disabled:opacity-40"
            onClick={() => { setOffset(offset + PAGE_SIZE); setSelected(new Set()) }}>Next</button>
        </div>
      </section>
    </>}
  </main>
}
