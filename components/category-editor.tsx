'use client'

import { Check } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { CategoryBadge, categoryMetadata } from './category-display'

export type CategoryOption = { value: string; label: string }
export type CategoryDetail = {
  transaction_id: string
  original_category: string | null
  override_category: string | null
  effective_category: string
  category_editable: boolean
}
export type CategoryMutationResult = Pick<
  CategoryDetail,
  'transaction_id' | 'original_category' | 'override_category' | 'effective_category'
>

export function categoryMutationRequest(category: string | null): Pick<RequestInit, 'method' | 'headers' | 'body'> {
  return category === null
    ? { method: 'DELETE' }
    : {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category }),
      }
}

export async function mutateCategoryOverride(
  transactionId: string,
  category: string | null,
  signal?: AbortSignal,
): Promise<CategoryMutationResult> {
  const response = await fetch(
    `/api/pft/review/transactions/${encodeURIComponent(transactionId)}/category-override`,
    { ...categoryMutationRequest(category), signal },
  )
  if (!response.ok) throw new Error('Category change could not be saved. Refresh and try again.')
  return response.json() as Promise<CategoryMutationResult>
}

export function mergeCategoryDetail<T extends CategoryDetail>(
  detail: T,
  changed: CategoryMutationResult,
): T {
  if (detail.transaction_id !== changed.transaction_id) return detail
  return {
    ...detail,
    original_category: changed.original_category,
    override_category: changed.override_category,
    effective_category: changed.effective_category,
  }
}

export function sortedCategoryOptions(options: CategoryOption[]) {
  return [...options].sort((left, right) => {
    if (left.value === 'UNCATEGORIZED') return 1
    if (right.value === 'UNCATEGORIZED') return -1
    return categoryMetadata(left.value).label.localeCompare(categoryMetadata(right.value).label)
  })
}

export default function CategoryEditor({ detail, options, busy, save }: {
  detail: CategoryDetail
  options: CategoryOption[]
  busy: boolean
  save: (detail: CategoryDetail, category: string | null) => Promise<boolean>
}) {
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState(detail.effective_category)
  const orderedOptions = useMemo(() => sortedCategoryOptions(options), [options])
  const selectedAvailable = options.some(option => option.value === selected)
  const panelId = `category-editor-${detail.transaction_id.replace(/[^A-Za-z0-9_-]/g, '-')}`

  useEffect(() => {
    setSelected(detail.effective_category)
  }, [detail.effective_category, detail.transaction_id])

  function toggle() {
    if (!open) setSelected(detail.effective_category)
    setOpen(value => !value)
  }

  async function persist(category: string | null) {
    if (await save(detail, category)) setOpen(false)
  }

  return <div className="mt-3 w-full text-sm">
    <div className="flex flex-wrap items-center gap-2">
      <CategoryBadge category={detail.effective_category} manual={detail.override_category !== null}
        editable={detail.category_editable} busy={busy} expanded={open} controls={panelId} onClick={toggle} />
    </div>

    {open && detail.category_editable && <div id={panelId} className="mt-2 rounded-md border bg-slate-50 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">Spending category</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Plaid category: {categoryMetadata(detail.original_category).label}
          </p>
        </div>
        {detail.override_category !== null && <button type="button" className="text-xs font-medium text-blue-700 underline"
          disabled={busy} onClick={() => void persist(null)}>Restore automatic</button>}
      </div>

      <div role="radiogroup" aria-label="Spending category" className="mt-3 grid gap-2 sm:grid-cols-2">
        {orderedOptions.map(option => {
          const metadata = categoryMetadata(option.value)
          const Icon = metadata.icon
          const checked = selected === option.value
          return <label key={option.value} className={`flex cursor-pointer items-center gap-2 rounded-md border bg-white px-3 py-2 text-xs font-medium outline-none transition focus-within:ring-2 focus-within:ring-blue-300 ${
            checked ? 'border-blue-500 bg-blue-50 text-blue-950' : 'border-slate-200 hover:border-slate-400'
          } ${busy ? 'cursor-default opacity-50' : ''}`}>
            <input type="radio" className="sr-only" name={`category-${detail.transaction_id}`}
              value={option.value} checked={checked} disabled={busy}
              onChange={() => setSelected(option.value)} />
            <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />
            <span className="min-w-0 flex-1">{metadata.label}</span>
            {checked && <Check aria-hidden="true" className="h-4 w-4 shrink-0" />}
          </label>
        })}
      </div>

      {!selectedAvailable && <p className="mt-2 text-xs text-red-700">This category is not available for manual selection.</p>}
      <div className="mt-3 flex justify-end gap-3">
        <button type="button" className="text-xs font-medium text-blue-700 underline" disabled={busy}
          onClick={() => { setSelected(detail.effective_category); setOpen(false) }}>Cancel</button>
        <button type="button" className="rounded-md bg-black px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          disabled={busy || !selectedAvailable} onClick={() => void persist(selected)}>
          {busy ? 'Saving…' : 'Save category'}
        </button>
      </div>
    </div>}
  </div>
}
