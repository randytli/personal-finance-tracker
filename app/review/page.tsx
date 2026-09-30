'use client'

import { PageNavigation, TransactionTools, TransactionTypeBadge, useTransactionPageSize } from '@/components/page-presentation'
import { Button } from '@/components/ui/button'
import { useCallback, useEffect, useRef, useState } from 'react'
import AccountBadge from '@/components/account-badge'
import BulkTransactionEditor, { bulkErrorMessage, type BulkEditRequest } from '@/components/bulk-transaction-editor'
import CategoryEditor, { mergeCategoryDetail, mutateCategoryOverride, type CategoryDetail } from '@/components/category-editor'
import BenefitCategoryEditor, { type BenefitCategoryDetail, type BenefitCategoryOption } from '@/components/benefit-category-editor'
import { CategoryBadge } from '@/components/category-display'
import LabelEditor, { mergeLabelDetail, type LabelDetail, useLabelOptions } from '@/components/label-editor'
import { SyncHealth, consistentJson, useSyncRefresh } from '@/components/sync-health'

const TYPES = ['expense', 'refund', 'income', 'card_benefit', 'payment', 'transfer', 'adjustment'] as const
type TransactionType = typeof TYPES[number] | 'reimbursement'
const CREDIT_TYPES = ['reimbursement', 'refund', 'income', 'transfer', 'payment', 'card_benefit', 'adjustment'] as const
const OUTGOING_TYPES = ['expense', 'transfer', 'payment', 'adjustment'] as const
const FILTERS = ['all', 'transfer', 'payment', 'income', 'refund', 'reimbursement', 'card_benefit', 'unclassified'] as const

type ReviewTransaction = CategoryDetail & BenefitCategoryDetail & LabelDetail & {
  transaction_id: string
  transaction_date: string
  institution_name: string
  account_name: string
  account_mask: string | null
  account_type: string
  merchant_name: string | null
  description: string | null
  amount: string
  plaid_category: string | null
  automatic_transaction_type: TransactionType | null
  effective_transaction_type: TransactionType | null
  override_transaction_type: TransactionType | null
  effective_is_internal_transfer: boolean | null
}

type Undo = { transaction: ReviewTransaction; transactionType: TransactionType }

export default function ReviewPage() {
  const [transactions, setTransactions] = useState<ReviewTransaction[]>([])
  const [total, setTotal] = useState(0)
  const [choices, setChoices] = useState<Record<string, TransactionType>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [optionsRetry, setOptionsRetry] = useState(0)
  const [loading, setLoading] = useState(true)
  const [undo, setUndo] = useState<Undo | null>(null)
  const [mode, setMode] = useState<'needs_review' | 'credits_transfers'>('needs_review')
  const [typeFilter, setTypeFilter] = useState('all')
  const [direction, setDirection] = useState<'incoming' | 'outgoing' | 'all'>('incoming')
  const [categoryOptions, setCategoryOptions] = useState<Array<{ value: string; label: string }>>([])
  const [benefitCategoryOptions, setBenefitCategoryOptions] = useState<BenefitCategoryOption[]>([])
  const [categoryBusy, setCategoryBusy] = useState(false)
  const pageSize = useTransactionPageSize()
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkStatus, setBulkStatus] = useState('')
  const requestId = useRef(0)
  const labelOptions = useLabelOptions()
  const sync = useSyncRefresh()

  useEffect(() => {
    let active = true
    fetch('/api/pft/review/categories').then(response => response.ok ? response.json() : Promise.reject())
      .then(data => { if (active) setCategoryOptions(data.categories || []) })
      .catch(() => { if (active) setError('Category options could not be loaded.') })
    return () => { active = false }
  }, [optionsRetry])

  useEffect(() => {
    let active = true
    fetch('/api/pft/review/benefit-categories').then(response => response.ok ? response.json() : Promise.reject())
      .then(data => { if (active) setBenefitCategoryOptions(data.categories || []) })
      .catch(() => { if (active) setError('Benefit category options could not be loaded.') })
    return () => { active = false }
  }, [optionsRetry])

  const load = useCallback(async () => {
    const id = ++requestId.current
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ mode, transaction_type: typeFilter, direction, limit: String(pageSize), offset: String(offset) })
      const [data] = await consistentJson([`/api/pft/review/transactions?${params}`], sync.check)
      if (id !== requestId.current) return
      if (offset > 0 && offset >= data.total) {
        setOffset(Math.max(0, Math.floor((data.total - 1) / pageSize) * pageSize))
        return
      }
      setTransactions(Array.isArray(data.transactions) ? data.transactions : [])
      setTotal(typeof data.total === 'number' ? data.total : 0)
    } catch {
      if (id !== requestId.current) return
      setError('Transactions needing review could not be loaded.')
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [mode, typeFilter, direction, offset, pageSize, sync.check])

  useEffect(() => {
    setSelected(new Set())
    void load()
    return () => { requestId.current++ }
  }, [load, sync.revision])

  function invalidateAfterEdit() {
    requestId.current++
    sync.invalidate()
  }

  async function save(transaction: ReviewTransaction) {
    const transactionType = choices[transaction.transaction_id]
    if (!transactionType) {
      setError('Choose a classification before saving.')
      return
    }
    setBusy(transaction.transaction_id)
    setError('')
    try {
      const response = await fetch(
        `/api/pft/review/transactions/${encodeURIComponent(transaction.transaction_id)}/override`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ transaction_type: transactionType }),
        },
      )
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail || 'save failed')
      }
      setUndo({ transaction, transactionType })
      setSelected(new Set())
      setChoices((current) => { const next = { ...current }; delete next[transaction.transaction_id]; return next })
      invalidateAfterEdit()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Classification could not be saved.')
    } finally {
      setBusy(null)
    }
  }

  async function clearOverride(transaction: ReviewTransaction) {
    setBusy(transaction.transaction_id)
    setError('')
    try {
      const response = await fetch(
        `/api/pft/review/transactions/${encodeURIComponent(transaction.transaction_id)}/override`,
        { method: 'DELETE' },
      )
      if (!response.ok) throw new Error('Undo could not be saved.')
      setUndo(null)
      setSelected(new Set())
      invalidateAfterEdit()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Undo could not be saved.')
    } finally {
      setBusy(null)
    }
  }

  function updateLabels(changed: LabelDetail) {
    setTransactions(current => current.map(transaction => mergeLabelDetail(transaction, changed)))
    invalidateAfterEdit()
  }

  function updateBenefitCategory(changed: BenefitCategoryDetail) {
    setTransactions(current => current.map(transaction => transaction.transaction_id === changed.transaction_id
      ? { ...transaction, ...changed } : transaction))
    invalidateAfterEdit()
  }

  async function saveCategory(detail: CategoryDetail, category: string | null): Promise<boolean> {
    setCategoryBusy(true)
    setError('')
    try {
      const changed = await mutateCategoryOverride(detail.transaction_id, category)
      setTransactions(current => current.map(transaction => mergeCategoryDetail(transaction, changed)))
      invalidateAfterEdit()
      return true
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Category change failed.')
      return false
    } finally { setCategoryBusy(false) }
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
      setSelected(new Set())
      setBulkStatus(`${body.changed_count} changed · ${body.unchanged_count} unchanged.`)
      invalidateAfterEdit()
      return true
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Bulk change could not be saved.')
      return false
    } finally { setBulkBusy(false) }
  }

  function toggleSelected(transactionId: string) {
    setSelected(current => {
      const next = new Set(current)
      if (next.has(transactionId)) next.delete(transactionId)
      else next.add(transactionId)
      return next
    })
  }

  const selectedTransactions = transactions.filter(transaction => selected.has(transaction.transaction_id))
  const classificationOptions = [
    { value: 'reimbursement' as const, label: 'Reimbursement',
      eligibleCount: selectedTransactions.filter(transaction => Number(transaction.amount) > 0
        && transaction.effective_is_internal_transfer !== true).length },
    { value: 'expense' as const, label: 'Expense',
      eligibleCount: selectedTransactions.filter(transaction => Number(transaction.amount) < 0
        && transaction.effective_is_internal_transfer !== true).length },
  ]

  return (
    <main className="mx-auto max-w-7xl px-4 pb-10 pt-4 sm:px-6 sm:pt-6">
      <PageNavigation current="Review" />
      <div className="mt-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{mode === 'needs_review' ? 'Needs Review' : 'Credits & Transfers'}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Classify ambiguous transactions without changing automatic rules.
          </p>
        </div>
        <p className="text-sm font-medium">{total} {mode === 'needs_review' ? 'remaining' : 'matching transactions'}</p>
      </div>
      <div className="mt-5"><SyncHealth status={sync.status} error={sync.error} onRetry={() => { void sync.check().catch(() => undefined) }} /></div>
      <section aria-label="Review controls" className="mt-6 rounded-lg border bg-card p-4 shadow-sm">
      <nav aria-label="Review views" className="flex flex-wrap gap-2">
        {(['needs_review', 'credits_transfers'] as const).map((view) => (
          <Button size="sm" variant={mode === view ? 'secondary' : 'ghost'} key={view} aria-pressed={mode === view} disabled={bulkBusy || busy !== null}
            onClick={() => { setMode(view); setDirection('incoming'); setOffset(0); setTypeFilter('all'); setChoices({}); setSelected(new Set()) }}>
            {view === 'needs_review' ? 'Needs Review' : 'Credits & Transfers'}
          </Button>
        ))}
      </nav>
      {mode === 'credits_transfers' && <div className="mt-4 flex flex-wrap gap-4">
        <label className="flex flex-wrap items-center gap-2 text-sm">Direction{' '}
          <select aria-label="Direction filter" value={direction} disabled={bulkBusy || busy !== null}
            className="min-h-9 max-w-full rounded-md border bg-background px-3 py-2"
            onChange={(event) => { setDirection(event.target.value as typeof direction); setOffset(0); setChoices({}); setSelected(new Set()) }}>
            <option value="incoming">Incoming</option><option value="outgoing">Outgoing</option><option value="all">All</option>
          </select>
        </label>
        <label className="flex flex-wrap items-center gap-2 text-sm">Effective type{' '}
          <select aria-label="Effective type filter" value={typeFilter} disabled={bulkBusy || busy !== null}
            className="min-h-9 max-w-full rounded-md border bg-background px-3 py-2"
            onChange={(event) => { setTypeFilter(event.target.value); setOffset(0); setChoices({}); setSelected(new Set()) }}>
            {FILTERS.map((type) => <option key={type} value={type}>{type === 'card_benefit' ? 'Card Benefit' : type.charAt(0).toUpperCase() + type.slice(1)}</option>)}
          </select>
        </label>
      </div>}

      </section>

      {undo && (
        <div className="mt-5 rounded-md border bg-white p-4 text-sm [overflow-wrap:anywhere]">
          Saved {undo.transactionType.replace('_', ' ')} for {undo.transaction.description || undo.transaction.merchant_name || 'transaction'}.
          <button className="ml-3 font-medium text-blue-700 underline" onClick={() => clearOverride(undo.transaction)} disabled={busy !== null}>Undo / Restore automatic</button>
        </div>
      )}
      {error && <p role="alert" className="mt-5 rounded-md bg-red-50 p-3 text-sm text-red-800">{error} <Button type="button" variant="ghost" size="sm" onClick={() => { setError(''); setOptionsRetry(value => value + 1); sync.invalidate() }}>Retry loading</Button></p>}
      {bulkStatus && <p role="status" className="mt-5 rounded-md border bg-slate-50 p-3 text-sm">{bulkStatus}</p>}
      {loading && <p className="mt-8 text-muted-foreground">Loading transactions…</p>}
      {!loading && transactions.length === 0 && !error && (
        <p className="mt-8 rounded-lg border bg-white p-8 text-center">{mode === 'needs_review' ? 'Nothing needs review.' : 'No matching credits or transfers.'}</p>
      )}

      {!loading && transactions.length > 0 && <div className="mt-6 rounded-t-lg border bg-muted/50 px-4 py-3">
        <label className="inline-flex items-center gap-2 text-sm font-medium">
          <input type="checkbox"
            checked={transactions.every(transaction => selected.has(transaction.transaction_id))}
            ref={element => { if (element) element.indeterminate = selected.size > 0 && !transactions.every(transaction => selected.has(transaction.transaction_id)) }}
            disabled={bulkBusy || busy !== null}
            onChange={event => setSelected(event.target.checked
              ? new Set(transactions.map(transaction => transaction.transaction_id)) : new Set())} />
          Select current page ({transactions.length})
        </label>
        {selected.size > 0 && <button type="button" className="ml-4 text-sm text-blue-700 underline"
          disabled={bulkBusy || busy !== null} onClick={() => setSelected(new Set())}>Clear selection</button>}
      </div>}

      <div className={transactions.length > 0 && !loading ? "divide-y overflow-hidden rounded-b-lg border border-t-0 bg-card shadow-sm" : undefined}>
        {!loading && transactions.map((transaction) => (
          <article key={transaction.transaction_id} className="p-4 sm:p-5">
            <div className="flex flex-wrap justify-between gap-3">
              <label className="pt-1">
                <input type="checkbox" checked={selected.has(transaction.transaction_id)}
                  disabled={bulkBusy || busy !== null} onChange={() => toggleSelected(transaction.transaction_id)}
                  aria-label={`Select ${transaction.merchant_name || transaction.description || 'transaction'}`} />
              </label>
              <div className="min-w-0 flex-1 basis-40">
                <h2 className="break-words font-medium">{transaction.merchant_name || transaction.description || 'Unknown transaction'}</h2>
                {transaction.description !== transaction.merchant_name && <p className="mt-1 break-words text-sm text-muted-foreground">{transaction.description}</p>}
                <div className="mt-2 flex flex-wrap gap-2">
                  <TransactionTypeBadge type={transaction.effective_transaction_type} manual={Boolean(transaction.override_transaction_type)} />
                  {!transaction.category_editable && <CategoryBadge category={transaction.effective_category} manual={transaction.override_category != null} />}
                </div>
                {transaction.override_transaction_type && <p className="mt-1 text-xs text-muted-foreground">
                  Automatic: {transaction.automatic_transaction_type?.replace(/_/g, ' ') || 'unclassified'}
                </p>}
                {mode === 'credits_transfers' && (transaction.effective_is_internal_transfer ||
                  transaction.effective_transaction_type === 'transfer' || transaction.effective_transaction_type === 'payment') &&
                  <p className="mt-2 inline-block rounded-full border border-slate-300 bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">
                    {transaction.effective_is_internal_transfer ? 'Confirmed internal transfer · excluded money movement' : 'Excluded money movement'}
                  </p>}
              </div>
              <p className="max-w-full shrink-0 font-semibold tabular-nums [overflow-wrap:anywhere]">{new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(transaction.amount))}</p>
            </div>
            {transaction.category_editable && <CategoryEditor detail={transaction} options={categoryOptions}
              busy={categoryBusy || bulkBusy || busy !== null} save={saveCategory} />}
            <TransactionTools>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <p>{transaction.transaction_date} · {transaction.institution_name} · {transaction.account_type}</p>
                <AccountBadge institutionName={transaction.institution_name} accountName={transaction.account_name}
                  accountMask={transaction.account_mask} accountType={transaction.account_type} />
                <div className="flex flex-wrap items-center gap-2"><span>Plaid category</span><CategoryBadge category={transaction.plaid_category} /></div>
              </div>
                <div className="flex flex-wrap items-center gap-2 md:justify-end">
              <select
                aria-label={`Classification for ${transaction.description || transaction.transaction_id}`}
                className="min-h-9 max-w-full rounded-md border bg-background px-3 py-2 text-sm"
                disabled={busy !== null || bulkBusy || (mode === 'credits_transfers' && transaction.effective_is_internal_transfer === true)}
                value={choices[transaction.transaction_id] || ''}
                onChange={(event) => setChoices((current) => ({
                  ...current,
                  [transaction.transaction_id]: event.target.value as TransactionType,
                }))}
              >
                <option value="">Choose classification</option>
                {(mode === 'credits_transfers' ? Number(transaction.amount) < 0 ? OUTGOING_TYPES : CREDIT_TYPES : TYPES)
                  .map((type) => <option key={type} value={type}>{type.replace('_', ' ')}</option>)}
              </select>
              <Button size="sm"
                disabled={bulkBusy || busy !== null || !choices[transaction.transaction_id] ||
                  (mode === 'credits_transfers' && transaction.effective_is_internal_transfer === true)}
                onClick={() => save(transaction)}
              >
                {busy === transaction.transaction_id ? 'Saving…' : 'Save'}
              </Button>
              {transaction.override_transaction_type && (
                <button className="text-sm text-blue-700 underline" disabled={bulkBusy || busy !== null}
                  onClick={() => clearOverride(transaction)}>Restore automatic</button>
              )}
            </div>

            </div>
            <div className="grid gap-x-5 md:grid-cols-2">
            <BenefitCategoryEditor detail={transaction} options={benefitCategoryOptions}
              disabled={bulkBusy || busy !== null} onChanged={updateBenefitCategory} />
            <LabelEditor detail={transaction} options={labelOptions.options}
              optionsLoading={labelOptions.loading} optionsError={labelOptions.error}
              disabled={bulkBusy} onRetryOptions={labelOptions.retry} onChanged={updateLabels} />
            </div>
            </TransactionTools>
          </article>
        ))}
      </div>
      {selected.size > 0 && <div className="min-w-0">
        <BulkTransactionEditor overviewStyle
          transactionIds={Array.from(selected)}
          categoryOptions={categoryOptions}
          benefitCategoryOptions={benefitCategoryOptions}
          labelOptions={labelOptions.options}
          allowClassification
          allowCategory
          allowBenefitCategory
          categoryIneligibleCount={selectedTransactions.filter(transaction => !transaction.category_editable).length}
          benefitIneligibleCount={selectedTransactions.filter(transaction => !transaction.benefit_category_editable).length}
          classificationOptions={classificationOptions}
          busy={bulkBusy}
          errorMessage={error} onApply={applyBulk}
          onClear={() => setSelected(new Set())}
        />
      </div>}
      <div className="mt-5 flex flex-wrap items-center gap-3 text-sm">
        <button disabled={loading || bulkBusy || busy !== null || offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))} className="disabled:opacity-40">Previous</button>
        <span>{total === 0 ? 0 : offset + 1}–{Math.min(offset + pageSize, total)} of {total}</span>
        <button disabled={loading || bulkBusy || busy !== null || offset + pageSize >= total} onClick={() => setOffset(offset + pageSize)} className="disabled:opacity-40">Next</button>
      </div>
    </main>
  )
}
