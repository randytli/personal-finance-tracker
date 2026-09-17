'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import AccountBadge from '@/components/account-badge'
import BulkTransactionEditor, { bulkErrorMessage, type BulkEditRequest } from '@/components/bulk-transaction-editor'
import CategoryEditor, { mergeCategoryDetail, mutateCategoryOverride, type CategoryDetail, type CategoryOption } from '@/components/category-editor'
import LabelEditor, { mergeLabelDetail, type LabelDetail, useLabelOptions } from '@/components/label-editor'

type MembershipMetrics = {
  gross_charges: string
  refunds: string
  card_benefits: string
  net_cost: string
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
  start_month: string
  end_month: string
  overall: MembershipMetrics
  months: Array<MembershipMetrics & { month: string }>
  accounts: MembershipAccount[]
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

function contributesToCost(detail: Detail) {
  const amount = Number(detail.amount)
  if (detail.is_internal_transfer) return false
  return (detail.transaction_type === 'expense' && detail.is_spending === true && amount < 0)
    || ((detail.transaction_type === 'refund' || detail.transaction_type === 'card_benefit') && amount > 0)
}

export default function MembershipsPage() {
  const [endMonth, setEndMonth] = useState(currentMonth)
  const [summary, setSummary] = useState<MembershipSummary | null>(null)
  const [accountId, setAccountId] = useState<string | null>(null)
  const [details, setDetails] = useState<Detail[]>([])
  const [total, setTotal] = useState(0)
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
    fetch(`/api/pft/analytics/memberships?end_month=${endMonth}`)
      .then(response => response.ok ? response.json() : Promise.reject())
      .then(data => { if (active) setSummary(data) })
      .catch(() => { if (active) setError('Membership costs could not be loaded.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [endMonth, revision])

  const startMonth = summary?.end_month === endMonth ? summary.start_month : null
  useEffect(() => {
    if (!startMonth) return
    let active = true
    setDetailLoading(true)
    const parameters = new URLSearchParams({
      start_month: startMonth,
      end_month: endMonth,
      label: 'MEMBERSHIP',
      limit: String(PAGE_SIZE),
      offset: String(offset),
    })
    if (accountId) parameters.set('account_id', accountId)
    fetch(`/api/pft/analytics/transactions?${parameters}`)
      .then(response => response.ok ? response.json() : Promise.reject())
      .then(data => {
        if (!active) return
        if (offset > 0 && offset >= data.total) {
          setOffset(Math.max(0, Math.floor((data.total - 1) / PAGE_SIZE) * PAGE_SIZE))
          return
        }
        setDetails(data.transactions || [])
        setTotal(data.total || 0)
      })
      .catch(() => { if (active) setError('Membership transactions could not be loaded.') })
      .finally(() => { if (active) setDetailLoading(false) })
    return () => { active = false }
  }, [startMonth, endMonth, accountId, offset, revision])

  const selectedAccount = summary?.accounts.find(account => account.account_id === accountId)
  const chartData = useMemo(() => (summary?.months || []).map(month => ({
    month: month.month,
    netCost: Number(month.net_cost),
    grossCharges: Number(month.gross_charges),
    refunds: Number(month.refunds),
    cardBenefits: Number(month.card_benefits),
  })), [summary])

  useEffect(() => {
    if (summary && accountId && !summary.accounts.some(account => account.account_id === accountId)) {
      changeAccount(null)
    }
  }, [summary, accountId])

  function changeAccount(nextId: string | null) {
    setAccountId(nextId)
    setOffset(0)
    setSelected(new Set())
    setDetails([])
    setStatus('')
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
        <p className="mt-1 text-sm text-muted-foreground">Recorded charges and credits on transactions labeled Membership.</p>
        {summary && <p className="mt-1 text-sm text-muted-foreground">
          {summary.start_month} through {summary.end_month} · trailing 12 months
          {endMonth === currentMonth() ? ' · current month is partial' : ''}
        </p>}
      </div>
      <label className="text-sm font-medium">Ending month{' '}
        <input type="month" value={endMonth} max={currentMonth()}
          className="ml-2 rounded-md border bg-white px-3 py-2"
          onChange={event => {
            if (!event.target.value) return
            setEndMonth(event.target.value)
            setSummary(null)
            setDetails([])
            setTotal(0)
            setError('')
            changeAccount(null)
          }} />
      </label>
    </header>
    {error && <p role="alert" className="mt-5 rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {status && <p role="status" className="mt-5 rounded-md border bg-slate-50 p-3 text-sm">{status}</p>}
    {loading && <p className="mt-6 text-sm text-muted-foreground">Loading membership costs…</p>}
    {summary && <>
      <section className="mt-7 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Overall membership costs">
        {([
          ['Gross charges', summary.overall.gross_charges],
          ['Refunds', summary.overall.refunds],
          ['Card benefits', summary.overall.card_benefits],
          ['Net cost', summary.overall.net_cost],
        ] as const).map(([name, value]) => <div key={name} className="rounded-lg border bg-white p-5 shadow-sm">
          <p className="text-sm text-muted-foreground">{name}</p>
          <p className="mt-1 text-2xl font-bold">{money(value)}</p>
        </div>)}
      </section>
      <p className="mt-3 text-xs text-muted-foreground">
        {summary.overall.membership_transaction_count} labeled transactions · {summary.overall.excluded_transaction_count} excluded from cost
        {summary.overall.unclassified_count > 0 ? ` (${summary.overall.unclassified_count} unclassified)` : ''}.
        {' '}Labeled payments, transfers, adjustments, income, and unclassified entries do not affect cost.
      </p>

      <section className="mt-8 rounded-lg border bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold">Monthly membership cost</h2>
        <div className="mt-4 h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ left: 10, right: 12 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" tickFormatter={value => value.slice(5)} />
              <YAxis tickFormatter={value => `$${value}`} />
              <Tooltip content={({ active, payload }) => {
                const month = payload?.[0]?.payload as typeof chartData[number] | undefined
                return active && month ? <div className="rounded-md border bg-white p-3 text-xs shadow">
                  <p className="font-semibold">{month.month}</p>
                  <p>Gross charges: {money(String(month.grossCharges))}</p>
                  <p>Refunds: {money(String(month.refunds))}</p>
                  <p>Card benefits: {money(String(month.cardBenefits))}</p>
                  <p className="font-semibold">Net cost: {money(String(month.netCost))}</p>
                </div> : null
              }} />
              <Line type="monotone" dataKey="netCost" name="Net cost" stroke="#2563eb" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-semibold">By account</h2>
        {summary.accounts.length === 0 && <p className="mt-3 text-sm text-muted-foreground">No Membership transactions in this period.</p>}
        <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {summary.accounts.map(account => <button key={account.account_id} type="button"
            aria-pressed={accountId === account.account_id}
            className={`rounded-lg border bg-white p-4 text-left shadow-sm hover:border-blue-500 ${accountId === account.account_id ? 'border-blue-600 ring-2 ring-blue-200' : ''}`}
            onClick={() => changeAccount(accountId === account.account_id ? null : account.account_id)}>
            <AccountBadge institutionName={account.institution_name} accountName={account.account_name}
              accountMask={account.account_mask} accountType={account.account_type} accountSubtype={account.account_subtype} />
            <p className="mt-3 text-lg font-semibold">{money(account.net_cost)} net cost</p>
            <div className="mt-2 grid grid-cols-2 gap-x-3 text-sm text-muted-foreground">
              <span>Gross {money(account.gross_charges)}</span><span>Refunds {money(account.refunds)}</span>
              <span>Benefits {money(account.card_benefits)}</span>
              <span>{account.membership_transaction_count} labeled transactions</span>
            </div>
            {account.excluded_transaction_count > 0 && <p className="mt-2 text-xs text-muted-foreground">
              {account.excluded_transaction_count} excluded from cost
            </p>}
          </button>)}
        </div>
      </section>

      <section className="mt-8 overflow-hidden rounded-lg border bg-white shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3 p-5">
          <div>
            <h2 className="text-lg font-semibold">Membership transactions</h2>
            <p className="text-sm text-muted-foreground">
              {selectedAccount ? `${selectedAccount.institution_name} · ${selectedAccount.account_name}` : 'All accounts'}
              {' · '}{total} labeled transactions in the reporting period
            </p>
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
              <p className="text-sm text-muted-foreground">{detail.transaction_date} · {detail.description} · {detail.transaction_type.replace(/_/g, ' ')}</p>
              {detail.institution_name && detail.account_name && <div className="mt-2">
                <AccountBadge institutionName={detail.institution_name} accountName={detail.account_name}
                  accountMask={detail.account_mask} accountType={detail.account_type || ''} accountSubtype={detail.account_subtype} />
              </div>}
            </div>
            <div className="text-right">
              <p className="font-semibold">{money(detail.amount)}</p>
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
