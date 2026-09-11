'use client'

import { useState } from 'react'

export type CategoryDetail = {
  transaction_id: string
  original_category: string | null
  override_category: string | null
  effective_category: string
  category_editable: boolean
}

export default function CategoryEditor({ detail, options, busy, save }: {
  detail: CategoryDetail
  options: Array<{ value: string; label: string }>
  busy: boolean
  save: (detail: CategoryDetail, category: string | null) => void
}) {
  const [selected, setSelected] = useState(detail.effective_category)
  return <div className="mt-3 text-sm">
    <p>{detail.effective_category}{detail.override_category ? ` · Manual category (Plaid: ${detail.original_category || 'Uncategorized'})` : ''}</p>
    {detail.category_editable && <>
      <select aria-label="Spending category" className="mt-2 rounded border p-2" value={selected} disabled={busy} onChange={e => setSelected(e.target.value)}>
        {!options.some(option => option.value === selected) && <option value={selected} disabled>{selected}</option>}
        {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
      <button type="button" className="ml-2 text-blue-700 underline" disabled={busy || !options.some(option => option.value === selected)} onClick={() => save(detail, selected)}>Save category</button>
    </>}
    {detail.override_category && <button type="button" className="ml-2 text-blue-700 underline" disabled={busy} onClick={() => save(detail, null)}>Restore automatic category</button>}
  </div>
}
