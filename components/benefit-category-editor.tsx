'use client'

export type BenefitCategoryOption = { value: string; label: string }
export type BenefitCategoryDetail = {
  transaction_id: string
  automatic_benefit_category: string | null
  override_benefit_category: string | null
  effective_benefit_category: string | null
  benefit_category_editable: boolean
}

export async function mutateBenefitCategory(transactionId: string, category: string | null) {
  const response = await fetch(`/api/pft/review/transactions/${encodeURIComponent(transactionId)}/benefit-category-override`,
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
  if (!detail.benefit_category_editable) return null
  return <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
    <span className="font-medium">Benefit category</span>
    <select aria-label="Benefit category" disabled={disabled} value={detail.override_benefit_category || detail.effective_benefit_category || 'UNCATEGORIZED'}
      className="rounded-md border bg-white px-2 py-1" onChange={async event => {
        const value = await mutateBenefitCategory(detail.transaction_id, event.target.value)
        onChanged(value)
      }}>
      {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
    {detail.override_benefit_category && <button type="button" disabled={disabled} className="text-blue-700 underline"
      onClick={async () => onChanged(await mutateBenefitCategory(detail.transaction_id, null))}>Restore automatic</button>}
  </div>
}
