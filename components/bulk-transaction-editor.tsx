'use client'

import { Button } from '@/components/ui/button'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
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

function measuredSpacerHeight(element: HTMLElement, container: HTMLElement | null) {
  const bottom = parseFloat(getComputedStyle(element).bottom) || 0
  const pagePadding = container ? parseFloat(getComputedStyle(container).paddingBottom) || 0 : 0
  const safeAreaPadding = container !== document.body ? parseFloat(getComputedStyle(document.body).paddingBottom) || 0 : 0
  // Page/footer padding and the body's safe area already reserve scroll space.
  return Math.max(0, Math.ceil(element.getBoundingClientRect().height + bottom + 16 - pagePadding - safeAreaPadding))
}

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
  errorMessage,
  onApply,
  onClear,
}: {
  transactionIds: string[]
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
  errorMessage?: string
  onApply: (request: BulkEditRequest) => Promise<boolean>
  onClear: () => void
}) {
  const [operation, setOperation] = useState<BulkOperation | ''>('')
  const [value, setValue] = useState('')
  const [reviewing, setReviewing] = useState(false)
  const applying = useRef(false)
  const toolbar = useRef<HTMLDivElement>(null)
  const placeholder = useRef<HTMLSpanElement>(null)
  const [portalRoot, setPortalRoot] = useState<HTMLElement | null>(null)
  const [spacerRoot, setSpacerRoot] = useState<HTMLElement | null>(null)
  const [spacerHeight, setSpacerHeight] = useState(0)
  const [keyboardInset, setKeyboardInset] = useState(0)
  const [availableHeight, setAvailableHeight] = useState<number | null>(null)
  const [applyFailed, setApplyFailed] = useState(false)
  useEffect(() => {
    setPortalRoot(document.body)
    setSpacerRoot(placeholder.current?.closest('main') || placeholder.current?.parentElement || document.body)
  }, [])
  // The viewport-fixed fallback stays visible after selecting near the top of a
  // long list. A portal avoids clipped ancestors; measurement reserves enough
  // space for confirmation/errors and the final row/footer on every viewport.
  useLayoutEffect(() => {
    const element = toolbar.current
    if (!element) return
    const measure = () => {
      setSpacerHeight(measuredSpacerHeight(element, spacerRoot))
    }
    const viewport = window.visualViewport
    const resize = () => {
      const height = viewport?.height ?? window.innerHeight
      // Pinch zoom must remain under the user's control.
      const inset = !viewport || viewport.scale > 1 ? 0
        : Math.max(0, window.innerHeight - height - viewport.offsetTop)
      setKeyboardInset(inset)
      setAvailableHeight(Math.floor(height * 0.7))
      measure()
    }
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(element)
    viewport?.addEventListener('resize', resize)
    viewport?.addEventListener('scroll', resize)
    window.addEventListener('resize', resize)
    resize()
    return () => {
      observer?.disconnect()
      viewport?.removeEventListener('resize', resize)
      viewport?.removeEventListener('scroll', resize)
      window.removeEventListener('resize', resize)
    }
  }, [portalRoot, spacerRoot])
  useLayoutEffect(() => {
    if (toolbar.current) {
      setSpacerHeight(measuredSpacerHeight(toolbar.current, spacerRoot))
    }
  }, [keyboardInset, reviewing, applyFailed, spacerRoot])
  const selectionKey = [...transactionIds].sort().join('\u0000')
  useEffect(() => { setReviewing(false); setApplyFailed(false) }, [selectionKey])
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
    setApplyFailed(false)
  }

  async function apply() {
    if (!operation || !valid || applying.current) return
    applying.current = true
    setApplyFailed(false)
    try {
      if (await onApply(bulkEditRequest(transactionIds, operation, value))) {
        setOperation(''); setValue(''); setReviewing(false)
      } else setApplyFailed(true)
    } finally { applying.current = false }
  }

  return <>
    <span ref={placeholder} hidden aria-hidden="true" />
    {spacerRoot && createPortal(<div data-bulk-spacer aria-hidden="true" style={{ height: spacerHeight }} />, spacerRoot)}
    {portalRoot && createPortal(<div ref={toolbar} data-bulk-toolbar
      style={{ bottom: `calc(max(12px, env(safe-area-inset-bottom)) + ${keyboardInset}px)`, maxHeight: availableHeight ?? '70dvh' }}
      className="fixed left-[max(1rem,env(safe-area-inset-left))] right-[max(1rem,env(safe-area-inset-right))] z-30 mx-auto max-w-6xl overflow-y-auto rounded-2xl border border-border bg-card/95 p-3 shadow-[0_12px_40px_rgb(15_23_42/0.14)] backdrop-blur sm:p-4">
    <div className="grid gap-3 sm:flex sm:flex-wrap sm:items-center">
      <div className="flex items-center justify-between gap-3">
      <p className="text-sm font-semibold">{transactionIds.length} selected <span className="font-normal text-muted-foreground">· this page only</span></p>
      <Button type="button" variant="link" size="inline" disabled={busy} className="sm:hidden" onClick={onClear}>Clear</Button>
      </div>
      <select aria-label="Bulk action" value={operation} disabled={busy}
        className="min-h-9 min-w-0 max-w-full rounded-md border border-input bg-card px-3 py-1.5 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
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
        className="min-h-9 min-w-0 max-w-full rounded-md border border-input bg-card px-3 py-1.5 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        onChange={event => { setValue(event.target.value); setReviewing(false) }}>
        <option value="">Choose {operation === 'set_classification' ? 'classification'
          : operation === 'set_category' ? 'category'
            : operation === 'set_benefit_category' ? 'benefit category' : 'label'}</option>
        {options.map(option => <option key={option.value} value={option.value}>
          {operation === 'set_classification' ? `${option.label} (${classificationOptions.find(item => item.value === option.value)?.eligibleCount || 0}/${transactionIds.length} eligible)`
            : operation === 'set_category' ? categoryMetadata(option.value).label : option.label}
        </option>)}
      </select>}
      {!reviewing && <Button type="button" size="sm" disabled={busy || !valid}
        onClick={() => setReviewing(true)}>Review changes</Button>}
      <Button type="button" variant="link" size="inline" disabled={busy} className="hidden sm:inline-flex" onClick={onClear}>Clear selection</Button>
    </div>
    {ineligibleCount > 0 && <p role="alert" className="mt-2 text-sm text-warning">
      {ineligibleCount} of {transactionIds.length} selected transactions are ineligible. Remove them before applying.
    </p>}
    {applyFailed && <p role="alert" className="mt-2 text-sm text-destructive">{errorMessage || 'Changes could not be saved. Try again.'}</p>}
    {reviewing && operation && valid && <div className="mt-3 rounded-lg border bg-muted/50 p-3 text-sm">
      <p><strong>{actionName}{hasValue ? `: ${valueName}` : ''}</strong> for {transactionIds.length} selected transactions.</p>
      {operation === 'set_category' && <p className="mt-1 text-muted-foreground">Existing manual categories will be replaced. Transactions may leave the current category view.</p>}
      {(operation === 'restore_category_auto' || operation === 'restore_benefit_category_auto') && <p className="mt-1 text-muted-foreground">A saved decision may be cleared even when a new value is unavailable. Classification is unchanged.</p>}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button type="button" size="sm" disabled={busy}
          onClick={() => void apply()}>{busy ? 'Applying…' : 'Apply to selected'}</Button>
        <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => setReviewing(false)}>Cancel</Button>
      </div>
    </div>}
    </div>, portalRoot)}
  </>
}
