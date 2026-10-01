'use client'

import { apiFetch } from '@/lib/api'
import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'

export type BenefitCategoryOption = { value: string; label: string }
export type BenefitCategoryDetail = {
  transaction_id: string
  automatic_benefit_category: string | null
  override_benefit_category: string | null
  effective_benefit_category: string | null
  benefit_category_editable: boolean
}

export async function mutateBenefitCategory(transactionId: string, category: string | null) {
  const response = await apiFetch(`/api/pft/review/transactions/${encodeURIComponent(transactionId)}/benefit-category-override`,
    category === null ? { method: 'DELETE' } : { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ benefit_category: category }) })
  if (!response.ok) throw new Error('Benefit category change could not be saved.')
  return response.json() as Promise<BenefitCategoryDetail>
}

export default function BenefitCategoryEditor({ detail, options, disabled, onChanged }: {
  detail: BenefitCategoryDetail
  options: BenefitCategoryOption[]
  disabled?: boolean
  onChanged: (value: BenefitCategoryDetail) => void
}) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const inFlight = useRef(false)
  async function save(category: string | null) {
    if (inFlight.current || disabled) return
    inFlight.current = true
    setSaving(true)
    setError('')
    try { onChanged(await mutateBenefitCategory(detail.transaction_id, category)) }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Benefit category change could not be saved.') }
    finally { inFlight.current = false; setSaving(false) }
  }
  if (!detail.benefit_category_editable) return null
  return <div className="flex flex-wrap items-center gap-2 text-xs">
    <span className="font-medium text-muted-foreground">Benefit category</span>
    <select aria-label="Benefit category" disabled={disabled || saving} value={detail.override_benefit_category || detail.effective_benefit_category || 'UNCATEGORIZED'}
      className="rounded-md border border-input bg-card px-2 py-1 font-medium shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onChange={event => void save(event.target.value)}>
      {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
    {detail.override_benefit_category && <Button type="button" variant="link" size="inline" className="text-xs" disabled={disabled || saving}
      onClick={() => void save(null)}>Restore automatic</Button>}
    {saving && <span role="status">Saving…</span>}
    {error && <span role="alert" className="w-full text-destructive">{error}</span>}
  </div>
}
