'use client'

import { useState } from 'react'

export type LabelDecision = 'include' | 'exclude'
export type LabelDetail = {
  transaction_id: string
  automatic_labels: string[]
  manual_label_decisions: Partial<Record<string, LabelDecision>>
  effective_labels: string[]
}

const LABEL = 'CHINA'

export default function LabelEditor({ detail, onChanged }: {
  detail: LabelDetail
  onChanged: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const automatic = detail.automatic_labels.includes(LABEL)
  const decision = detail.manual_label_decisions[LABEL]

  async function update(next: LabelDecision | null) {
    setBusy(true)
    setError('')
    try {
      const response = await fetch(
        `/api/pft/review/transactions/${encodeURIComponent(detail.transaction_id)}/labels/${LABEL}`,
        {
          method: next === null ? 'DELETE' : 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: next === null ? undefined : JSON.stringify({ decision: next }),
        },
      )
      if (!response.ok) throw new Error('Label change could not be saved.')
      onChanged()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Label change failed.')
    } finally {
      setBusy(false)
    }
  }

  return <div className="mt-3 text-sm">
    <div className="flex flex-wrap items-center gap-2">
      {detail.effective_labels.map(label => (
        <span key={label} className="rounded-full border border-red-300 bg-red-50 px-2 py-1 text-xs font-medium text-red-900">
          {label}{detail.manual_label_decisions[label] === 'include' ? ' · manual' : ' · automatic'}
        </span>
      ))}
      {!decision && <button type="button" className="text-blue-700 underline" disabled={busy}
        onClick={() => update(automatic ? 'exclude' : 'include')}>
        {automatic ? 'Exclude CHINA' : 'Add CHINA'}
      </button>}
      {decision && <button type="button" className="text-blue-700 underline" disabled={busy}
        onClick={() => update(null)}>Restore automatic CHINA label</button>}
    </div>
    {decision === 'exclude' && <p className="mt-1 text-xs text-muted-foreground">Automatic CHINA label manually excluded.</p>}
    {error && <p role="alert" className="mt-1 text-xs text-red-700">{error}</p>}
  </div>
}
