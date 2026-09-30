'use client'

import { cn } from '@/lib/utils'
import { buttonVariants } from '@/components/ui/button'
import { useEffect, useMemo, useRef, useState } from 'react'
import { categoryMetadata } from './category-display'
import { sortedCategoryOptions, type CategoryOption } from './category-editor'
import type { LabelOption } from './label-editor'
import type { BenefitCategoryOption } from './benefit-category-editor'

export type BulkOperation = 'set_classification' | 'restore_classification_auto' | 'set_category' | 'restore_category_auto' | 'set_benefit_category' | 'restore_benefit_category_auto' | 'include_label' | 'exclude_label' | 'restore_label_auto'
export type BulkEditRequest = {
  transaction_ids: string[]
  operation: BulkOperation
  transaction_type?: 'expense' | 'reimbursement'
  category?: string
  benefit_category?: string
  label?: string
}
export type BulkClassificationOption = {
  value: 'expense' | 'reimbursement'
  label: string
  eligibleCount: number
}

const noValue = new Set<BulkOperation>(['restore_classification_auto', 'restore_category_auto', 'restore_benefit_category_auto'])

export function bulkEditRequest(
  transactionIds: string[],
  operation: BulkOperation,
  value = '',
): BulkEditRequest {
  return {
    transaction_ids: [...transactionIds].sort(),
    operation,
    ...(operation === 'set_classification' ? { transaction_type: value as 'expense' | 'reimbursement' }
      : operation === 'set_category' ? { category: value }
        : operation === 'set_benefit_category' ? { benefit_category: value }
          : noValue.has(operation) ? {} : { label: value }),
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
  overviewStyle = false,
  categoryOptions,
  benefitCategoryOptions = [],
  labelOptions,
  categoryIneligibleCount = 0,
  benefitIneligibleCount = 0,
  classificationOptions = [],
  allowClassification = false,
  allowCategory = false,
  allowBenefitCategory = false,
  busy = false,
  onApply,
  onClear,
}: {
  transactionIds: string[]
  overviewStyle?: boolean
  categoryOptions: CategoryOption[]
  benefitCategoryOptions?: BenefitCategoryOption[]
  labelOptions: LabelOption[]
  categoryIneligibleCount?: number
  benefitIneligibleCount?: number
  classificationOptions?: BulkClassificationOption[]
  allowClassification?: boolean
  allowCategory?: boolean
  allowBenefitCategory?: boolean
  busy?: boolean
  onApply: (request: BulkEditRequest) => Promise<boolean>
  onClear: () => void
}) {
  const [operation, setOperation] = useState<BulkOperation | ''>('')
  const [value, setValue] = useState('')
  const [reviewing, setReviewing] = useState(false)
  const applying = useRef(false)
  const selectionKey = [...transactionIds].sort().join('\u0000')
  useEffect(() => { setReviewing(false) }, [selectionKey])
  const categories = useMemo(() => sortedCategoryOptions(categoryOptions), [categoryOptions])
  const hasValue = operation !== '' && !noValue.has(operation)
  const options = operation === 'set_classification' ? classificationOptions
    : operation === 'set_category' ? categories
      : operation === 'set_benefit_category' ? benefitCategoryOptions : labelOptions
  const classification = classificationOptions.find(option => option.value === value)
  const ineligibleCount = operation === 'set_classification'
    ? transactionIds.length - (classification?.eligibleCount || 0)
    : operation === 'set_category' ? categoryIneligibleCount
      : operation === 'set_benefit_category' ? benefitIneligibleCount : 0
  const valid = Boolean(operation && (!hasValue || value) && ineligibleCount === 0 && (!hasValue || options.length > 0))
  const actionName = operation === 'set_classification' ? 'Set classification'
    : operation === 'restore_classification_auto' ? 'Restore classification to Auto'
    : operation === 'set_category' ? 'Set category'
    : operation === 'restore_category_auto' ? 'Restore category to Auto'
    : operation === 'set_benefit_category' ? 'Set benefit category'
    : operation === 'restore_benefit_category_auto' ? 'Restore benefit category to Auto'
    : operation === 'include_label' ? 'Add label'
      : operation === 'exclude_label' ? 'Exclude label' : 'Restore label to Auto'
  const valueName = operation === 'set_classification' ? classification?.label || value
    : operation === 'set_category'
    ? categoryMetadata(value).label
    : options.find(option => option.value === value)?.label || value

  function chooseOperation(next: BulkOperation | '') {
    setOperation(next)
    setValue('')
    setReviewing(false)
  }

  async function apply() {
    if (!operation || !valid || applying.current) return
    applying.current = true
    try {
      if (await onApply(bulkEditRequest(transactionIds, operation, value))) {
        setOperation(''); setValue(''); setReviewing(false)
      }
    } finally { applying.current = false }
  }

  return <div data-bulk-toolbar className={cn("fixed bottom-[max(12px,env(safe-area-inset-bottom))] left-1/2 z-30 w-[calc(100%-2rem)] max-w-5xl -translate-x-1/2 rounded-lg border border-slate-300 bg-white p-3 shadow-lg", overviewStyle && "max-h-[70dvh] max-w-7xl overflow-y-auto border-border bg-card p-4 shadow-lg")}>
    <div className="grid gap-3 sm:flex sm:flex-wrap sm:items-center">
      <div className="flex items-center justify-between gap-3">
      <p className="text-sm font-semibold">{transactionIds.length} selected <span className="font-normal text-muted-foreground">· this page only</span></p>
      <button type="button" disabled={busy} className="text-sm text-blue-700 underline sm:hidden" onClick={onClear}>Clear</button>
      </div>
      <select aria-label="Bulk action" value={operation} disabled={busy}
        className={overviewStyle ? "min-h-9 min-w-0 max-w-full rounded-md border bg-background px-3 py-2 text-sm" : "rounded-md border bg-white px-3 py-2 text-sm"}
        onChange={event => chooseOperation(event.target.value as BulkOperation | '')}>
        <option value="">Choose bulk action</option>
        {allowClassification && <option value="set_classification">Set Classification</option>}
        {allowClassification && <option value="restore_classification_auto">Restore Classification to Auto</option>}
        {allowCategory && <option value="set_category">Set Category</option>}
        {allowCategory && <option value="restore_category_auto">Restore Category to Auto</option>}
        {allowBenefitCategory && <option value="set_benefit_category">Set Benefit Category</option>}
        {allowBenefitCategory && <option value="restore_benefit_category_auto">Restore Benefit Category to Auto</option>}
        <option value="include_label">Add Label</option>
        <option value="exclude_label">Exclude Label</option>
        <option value="restore_label_auto">Restore Label to Auto</option>
      </select>
      {hasValue && <select aria-label={operation === 'set_classification' ? 'Bulk classification'
        : operation === 'set_category' ? 'Bulk category'
          : operation === 'set_benefit_category' ? 'Bulk benefit category' : 'Bulk label'}
        value={value} disabled={busy || options.length === 0}
        className={overviewStyle ? "min-h-9 min-w-0 max-w-full rounded-md border bg-background px-3 py-2 text-sm" : "rounded-md border bg-white px-3 py-2 text-sm"}
        onChange={event => { setValue(event.target.value); setReviewing(false) }}>
        <option value="">Choose {operation === 'set_classification' ? 'classification'
          : operation === 'set_category' ? 'category'
            : operation === 'set_benefit_category' ? 'benefit category' : 'label'}</option>
        {options.map(option => <option key={option.value} value={option.value}>
          {operation === 'set_classification' ? `${option.label} (${classificationOptions.find(item => item.value === option.value)?.eligibleCount || 0}/${transactionIds.length} eligible)`
            : operation === 'set_category' ? categoryMetadata(option.value).label : option.label}
        </option>)}
      </select>}
      {!reviewing && <button type="button" disabled={busy || !valid}
        className={overviewStyle ? buttonVariants({ size: 'sm' }) : "rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-40"}
        onClick={() => setReviewing(true)}>Review changes</button>}
      <button type="button" disabled={busy} className="hidden text-sm text-blue-700 underline sm:inline" onClick={onClear}>Clear selection</button>
    </div>
    {ineligibleCount > 0 && <p role="alert" className="mt-2 text-sm text-amber-800">
      {ineligibleCount} of {transactionIds.length} selected transactions are ineligible. Remove them before applying.
    </p>}
    {reviewing && operation && valid && <div className="mt-3 rounded-md bg-slate-50 p-3 text-sm">
      <p><strong>{actionName}{hasValue ? `: ${valueName}` : ''}</strong> for {transactionIds.length} selected transactions.</p>
      {operation === 'set_category' && <p className="mt-1 text-muted-foreground">Existing manual categories will be replaced. Transactions may leave the current category view.</p>}
      {(operation === 'restore_category_auto' || operation === 'restore_benefit_category_auto') && <p className="mt-1 text-muted-foreground">A saved decision may be cleared even when a new value is unavailable. Classification is unchanged.</p>}
      <div className="mt-3 flex gap-3">
        <button type="button" disabled={busy} className={overviewStyle ? buttonVariants({ size: 'sm' }) : "rounded-md bg-black px-4 py-2 font-medium text-white disabled:opacity-50"}
          onClick={() => void apply()}>{busy ? 'Applying…' : 'Apply to selected'}</button>
        <button type="button" disabled={busy} className="text-blue-700 underline" onClick={() => setReviewing(false)}>Cancel</button>
      </div>
    </div>}
  </div>
}
