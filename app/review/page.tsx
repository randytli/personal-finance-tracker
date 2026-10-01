'use client'

import { Amount, ControlField, DayGroup, LoadingState, MoreTags, PageHeader, PageNavigation, Pagination, SelectAllBar, TransactionRow, TransactionTools, TransactionTypeBadge, cardClassName, fieldClassName, groupByDay, pageClassName, useTransactionPageSize } from '@/components/page-presentation'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { CircleAlert, CircleCheck } from 'lucide-react'
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

  const controlsBusy = bulkBusy || busy !== null
  return (
    <>
    <PageNavigation current="Review" />
    <main className={pageClassName}>
      <PageHeader title={mode === 'needs_review' ? 'Needs Review' : 'Credits & Transfers'}
        description="Classify ambiguous transactions without changing automatic rules."
        actions={<Badge variant={mode === 'needs_review' && total > 0 ? 'warning' : 'secondary'} className="text-sm tabular-nums">
          {total} {mode === 'needs_review' ? 'remaining' : 'matching transactions'}
        </Badge>} />
      <div className="mt-5"><SyncHealth status={sync.status} error={sync.error} onRetry={() => { void sync.check().catch(() => undefined) }} /></div>
      <section aria-label="Review controls" className="mt-6 flex flex-wrap items-end justify-between gap-3">
        <nav aria-label="Review views" className="inline-flex flex-wrap gap-0.5 rounded-full border bg-card p-1">
          {(['needs_review', 'credits_transfers'] as const).map((view) => (
            <Button size="sm" variant="ghost" key={view} aria-pressed={mode === view} disabled={controlsBusy}
              className={cn('text-muted-foreground hover:bg-accent', mode === view && 'bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground')}
              onClick={() => { setMode(view); setDirection('incoming'); setOffset(0); setTypeFilter('all'); setChoices({}); setSelected(new Set()) }}>
              {view === 'needs_review' ? 'Needs Review' : 'Credits & Transfers'}
            </Button>
          ))}
        </nav>
        {mode === 'credits_transfers' && <div className="flex w-full flex-wrap gap-3 sm:w-auto">
          <ControlField label="Direction">
            <select aria-label="Direction filter" value={direction} disabled={controlsBusy} className={fieldClassName}
              onChange={(event) => { setDirection(event.target.value as typeof direction); setOffset(0); setChoices({}); setSelected(new Set()) }}>
              <option value="incoming">Incoming</option><option value="outgoing">Outgoing</option><option value="all">All</option>
            </select>
          </ControlField>
          <ControlField label="Effective type">
            <select aria-label="Effective type filter" value={typeFilter} disabled={controlsBusy} className={fieldClassName}
              onChange={(event) => { setTypeFilter(event.target.value); setOffset(0); setChoices({}); setSelected(new Set()) }}>
              {FILTERS.map((type) => <option key={type} value={type}>{type === 'card_benefit' ? 'Card Benefit' : type.charAt(0).toUpperCase() + type.slice(1)}</option>)}
            </select>
          </ControlField>
        </div>}
      </section>

      {undo && (
        <Alert variant="info" className="mt-4">
          <CircleCheck aria-hidden="true" />
          <span className="min-w-0">Saved {undo.transactionType.replace('_', ' ')} for {undo.transaction.description || undo.transaction.merchant_name || 'transaction'}.</span>
          <Button type="button" variant="link" size="inline" onClick={() => clearOverride(undo.transaction)} disabled={busy !== null}>Undo / Restore automatic</Button>
        </Alert>
      )}
      {error && <Alert role="alert" variant="destructive" className="mt-4"><CircleAlert aria-hidden="true" /><span className="min-w-0 flex-1">{error}</span> <Button type="button" variant="outline" size="sm" onClick={() => { setError(''); setOptionsRetry(value => value + 1); sync.invalidate() }}>Retry loading</Button></Alert>}
      {bulkStatus && <Alert role="status" variant="success" className="mt-4"><CircleCheck aria-hidden="true" />{bulkStatus}</Alert>}
      {loading && <LoadingState label="Loading transactions…" rows={4} />}
      {!loading && transactions.length === 0 && !error && (
        <div className={cn(cardClassName, 'mt-4 flex flex-col items-center gap-2 px-6 py-12 text-center')}>
          <CircleCheck aria-hidden="true" className="size-8 text-success" />
          <p className="font-medium">{mode === 'needs_review' ? 'Nothing needs review.' : 'No matching credits or transfers.'}</p>
          <p className="text-sm text-muted-foreground">{mode === 'needs_review' ? 'Every transaction in scope has a classification.' : 'Try another direction or type filter.'}</p>
        </div>
      )}

      {!loading && transactions.length > 0 && <section aria-labelledby="review-list-title" className={cn(cardClassName, 'mt-4')}>
      <h2 id="review-list-title" className="px-4 pt-4 text-base font-semibold sm:px-5 sm:pt-5">{mode === 'needs_review' ? 'Transactions to review' : 'Credits and transfers'}</h2>
      <SelectAllBar className="mt-1">
        <label className="inline-flex items-center gap-2 text-sm font-medium">
          <input type="checkbox"
            checked={transactions.every(transaction => selected.has(transaction.transaction_id))}
            ref={element => { if (element) element.indeterminate = selected.size > 0 && !transactions.every(transaction => selected.has(transaction.transaction_id)) }}
            disabled={controlsBusy}
            onChange={event => setSelected(event.target.checked
              ? new Set(transactions.map(transaction => transaction.transaction_id)) : new Set())} />
          Select current page ({transactions.length})
        </label>
        {selected.size > 0 && <Button type="button" variant="link" size="inline"
          disabled={controlsBusy} onClick={() => setSelected(new Set())}>Clear selection</Button>}
      </SelectAllBar>

      <div className="px-1.5 pb-2">
        {groupByDay(transactions, transaction => transaction.transaction_date).map(group => <DayGroup key={group.date} date={group.date}>
        {group.rows.map((transaction) => (
          <TransactionRow as="article" key={transaction.transaction_id}
            select={<label>
              <input type="checkbox" checked={selected.has(transaction.transaction_id)}
                disabled={controlsBusy} onChange={() => toggleSelected(transaction.transaction_id)}
                aria-label={`Select ${transaction.merchant_name || transaction.description || 'transaction'}`} />
            </label>}
            title={<h2 className="break-words font-medium">{transaction.merchant_name || transaction.description || 'Unknown transaction'}</h2>}
            meta={<>
              {transaction.description !== transaction.merchant_name && transaction.description}
              {mode === 'credits_transfers' && (transaction.effective_is_internal_transfer ||
                transaction.effective_transaction_type === 'transfer' || transaction.effective_transaction_type === 'payment') &&
                <Badge variant="muted" className="mt-1 flex w-fit">
                  {transaction.effective_is_internal_transfer ? 'Confirmed internal transfer · excluded money movement' : 'Excluded money movement'}
                </Badge>}
            </>}
            pill={transaction.category_editable
              ? <CategoryEditor detail={transaction} options={categoryOptions} busy={categoryBusy || controlsBusy} save={saveCategory} />
              : <CategoryBadge category={transaction.effective_category} manual={transaction.override_category != null} />}
            amount={<Amount value={transaction.amount}>{new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(transaction.amount))}</Amount>}>
            <TransactionTools count={transaction.override_transaction_type ? 5 : 4}>
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  <MoreTags count={transaction.override_transaction_type ? 5 : 4}>
                    <TransactionTypeBadge type={transaction.effective_transaction_type} manual={Boolean(transaction.override_transaction_type)} />
                    {transaction.override_transaction_type && <span className="text-xs text-muted-foreground">
                      Automatic: {transaction.automatic_transaction_type?.replace(/_/g, ' ') || 'unclassified'}
                    </span>}
                    <AccountBadge institutionName={transaction.institution_name} accountName={transaction.account_name}
                      accountMask={transaction.account_mask} accountType={transaction.account_type} />
                    <span className="min-w-0 truncate" title={`${transaction.institution_name} · ${transaction.account_type}`}>{transaction.institution_name} · {transaction.account_type}</span>
                    <span className="flex flex-wrap items-center gap-1.5"><span>Plaid category</span><CategoryBadge category={transaction.plaid_category} /></span>
                  </MoreTags>
                  <BenefitCategoryEditor detail={transaction} options={benefitCategoryOptions}
                    disabled={controlsBusy} onChanged={updateBenefitCategory} />
                  <LabelEditor detail={transaction} options={labelOptions.options}
                    optionsLoading={labelOptions.loading} optionsError={labelOptions.error}
                    disabled={bulkBusy} onRetryOptions={labelOptions.retry} onChanged={updateLabels} />
                </div>
                <div className="flex flex-wrap items-center gap-2 md:justify-end">
                  <select
                    aria-label={`Classification for ${transaction.description || transaction.transaction_id}`}
                    className={fieldClassName}
                    disabled={controlsBusy || (mode === 'credits_transfers' && transaction.effective_is_internal_transfer === true)}
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
                    disabled={controlsBusy || !choices[transaction.transaction_id] ||
                      (mode === 'credits_transfers' && transaction.effective_is_internal_transfer === true)}
                    onClick={() => save(transaction)}
                  >
                    {busy === transaction.transaction_id ? 'Saving…' : 'Save'}
                  </Button>
                  {transaction.override_transaction_type && (
                    <Button type="button" variant="link" size="inline" disabled={controlsBusy}
                      onClick={() => clearOverride(transaction)}>Restore automatic</Button>
                  )}
                </div>
              </div>
            </TransactionTools>
          </TransactionRow>
        ))}
        </DayGroup>)}
      </div>
      </section>}
      {selected.size > 0 && <div className="min-w-0">
        <BulkTransactionEditor
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
      <Pagination className="mt-4" offset={offset} pageSize={pageSize} total={total}
        disabled={loading || controlsBusy} onPage={setOffset} />
    </main>
    </>
  )
}
