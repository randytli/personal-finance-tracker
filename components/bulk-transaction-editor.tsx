'use client'

import { useMemo, useState } from 'react'
import { categoryMetadata } from './category-display'
import { sortedCategoryOptions, type CategoryOption } from './category-editor'
import type { LabelOption } from './label-editor'

export type BulkOperation = 'set_classification' | 'set_category' | 'include_label' | 'exclude_label' | 'restore_label_auto'
export type BulkEditRequest = {
  transaction_ids: string[]
  operation: BulkOperation
  transaction_type?: 'expense' | 'reimbursement'
  category?: string
  label?: string
}
export type BulkClassificationOption = {
  value: 'expense' | 'reimbursement'
  label: string
  eligibleCount: number
}

export function bulkEditRequest(
  transactionIds: string[],
  operation: BulkOperation,
  value: string,
): BulkEditRequest {
  return {
    transaction_ids: [...transactionIds].sort(),
    operation,
    ...(operation === 'set_classification' ? { transaction_type: value as 'expense' | 'reimbursement' }
      : operation === 'set_category' ? { category: value } : { label: value }),
  }
}

export function bulkErrorMessage(body: unknown, fallback = 'Bulk change could not be saved.') {
  if (!body || typeof body !== 'object') return fallback
  const detail = (body as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (!detail || typeof detail !== 'object') return fallback
  const value = detail as { message?: unknown; ineligible_count?: unknown; unavailable_count?: unknown }
  const count = typeof value.ineligible_count === 'number'
    ? value.ineligible_count
    : typeof value.unavailable_count === 'number' ? value.unavailable_count : null
  return `${typeof value.message === 'string' ? value.message : fallback}${count === null ? '' : ` (${count})`}`
}

export default function BulkTransactionEditor({
  transactionIds,
  categoryOptions,
  labelOptions,
  categoryIneligibleCount = 0,
  classificationOptions = [],
  allowClassification = false,
  allowCategory = false,
  busy = false,
  onApply,
  onClear,
}: {
  transactionIds: string[]
  categoryOptions: CategoryOption[]
  labelOptions: LabelOption[]
  categoryIneligibleCount?: number
  classificationOptions?: BulkClassificationOption[]
  allowClassification?: boolean
  allowCategory?: boolean
  busy?: boolean
  onApply: (request: BulkEditRequest) => Promise<boolean>
  onClear: () => void
}) {
  const [operation, setOperation] = useState<BulkOperation | ''>('')
  const [value, setValue] = useState('')
  const [reviewing, setReviewing] = useState(false)
  const categories = useMemo(() => sortedCategoryOptions(categoryOptions), [categoryOptions])
  const options = operation === 'set_classification' ? classificationOptions
    : operation === 'set_category' ? categories : labelOptions
  const categoryUnavailable = operation === 'set_category' && categoryIneligibleCount > 0
  const classification = classificationOptions.find(option => option.value === value)
  const classificationIneligibleCount = operation === 'set_classification'
    ? transactionIds.length - (classification?.eligibleCount || 0) : 0
  const classificationUnavailable = operation === 'set_classification' && classificationIneligibleCount > 0
  const actionName = operation === 'set_classification' ? 'Set classification'
    : operation === 'set_category' ? 'Set category'
    : operation === 'include_label' ? 'Add label'
      : operation === 'exclude_label' ? 'Exclude label' : 'Restore label to Auto'
  const valueName = operation === 'set_classification' ? classification?.label || value
    : operation === 'set_category'
    ? categoryMetadata(value).label
    : labelOptions.find(option => option.value === value)?.label || value

  function chooseOperation(next: BulkOperation | '') {
    setOperation(next)
    setValue('')
    setReviewing(false)
  }

  async function apply() {
    if (!operation || !value) return
    if (await onApply(bulkEditRequest(transactionIds, operation, value))) {
      setOperation('')
      setValue('')
      setReviewing(false)
    }
  }

  return <div className="sticky bottom-3 z-10 rounded-lg border border-slate-300 bg-white p-3 shadow-lg">
    <div className="flex flex-wrap items-center gap-3">
      <p className="text-sm font-semibold">{transactionIds.length} selected <span className="font-normal text-muted-foreground">· this page only</span></p>
      <select aria-label="Bulk action" value={operation} disabled={busy}
        className="rounded-md border bg-white px-3 py-2 text-sm"
        onChange={event => chooseOperation(event.target.value as BulkOperation | '')}>
        <option value="">Choose bulk action</option>
        {allowClassification && <option value="set_classification">Set Classification</option>}
        {allowCategory && <option value="set_category">Set Category</option>}
        <option value="include_label">Add Label</option>
        <option value="exclude_label">Exclude Label</option>
        <option value="restore_label_auto">Restore Label to Auto</option>
      </select>
      {operation && <select aria-label={operation === 'set_classification' ? 'Bulk classification'
        : operation === 'set_category' ? 'Bulk category' : 'Bulk label'}
        value={value} disabled={busy || categoryUnavailable || options.length === 0}
        className="rounded-md border bg-white px-3 py-2 text-sm"
        onChange={event => { setValue(event.target.value); setReviewing(false) }}>
        <option value="">Choose {operation === 'set_classification' ? 'classification'
          : operation === 'set_category' ? 'category' : 'label'}</option>
        {options.map(option => <option key={option.value} value={option.value}>
          {operation === 'set_classification' ? `${option.label} (${classificationOptions.find(item => item.value === option.value)?.eligibleCount || 0}/${transactionIds.length} eligible)`
            : operation === 'set_category' ? categoryMetadata(option.value).label : option.label}
        </option>)}
      </select>}
      {!reviewing && <button type="button" disabled={busy || !operation || !value || categoryUnavailable || classificationUnavailable}
        className="rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        onClick={() => setReviewing(true)}>Review changes</button>}
      <button type="button" disabled={busy} className="text-sm text-blue-700 underline" onClick={onClear}>Clear selection</button>
    </div>
    {categoryUnavailable && <p role="alert" className="mt-2 text-sm text-amber-800">
      Set Category is unavailable: {categoryIneligibleCount} selected {categoryIneligibleCount === 1 ? 'transaction is' : 'transactions are'} not an eligible expense or refund.
    </p>}
    {operation === 'set_classification' && value && <p className={`mt-2 text-sm ${classificationUnavailable ? 'text-amber-800' : 'text-muted-foreground'}`}>
      {classification?.eligibleCount || 0} of {transactionIds.length} selected transactions are eligible.
      {classificationUnavailable && ` ${classificationIneligibleCount} must be removed before applying.`}
    </p>}
    {reviewing && operation && value && !categoryUnavailable && !classificationUnavailable && <div className="mt-3 rounded-md bg-slate-50 p-3 text-sm">
      <p><strong>{actionName}:</strong> {valueName} for {transactionIds.length} selected transactions.</p>
      {operation === 'set_category' && <p className="mt-1 text-muted-foreground">Existing manual categories will be replaced. Transactions may leave the current category view.</p>}
      <div className="mt-3 flex gap-3">
        <button type="button" disabled={busy} className="rounded-md bg-black px-4 py-2 font-medium text-white disabled:opacity-50"
          onClick={() => void apply()}>{busy ? 'Applying…' : 'Apply to selected'}</button>
        <button type="button" disabled={busy} className="text-blue-700 underline" onClick={() => setReviewing(false)}>Cancel</button>
      </div>
    </div>}
  </div>
}
