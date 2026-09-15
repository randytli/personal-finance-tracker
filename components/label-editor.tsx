'use client'

import { ChevronDown, Pencil, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type LabelDecision = 'include' | 'exclude'
export type LabelChoice = LabelDecision | 'auto'
export type LabelOption = { value: string; label: string }
export type LabelDetail = {
  transaction_id: string
  automatic_labels: string[]
  manual_label_decisions: Partial<Record<string, LabelDecision>>
  effective_labels: string[]
}

export function labelChoice(detail: LabelDetail, label: string): LabelChoice {
  return detail.manual_label_decisions[label] || 'auto'
}

export function labelMutationRequest(choice: LabelChoice): Pick<RequestInit, 'method' | 'headers' | 'body'> {
  return choice === 'auto'
    ? { method: 'DELETE' }
    : {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision: choice }),
      }
}

export function mergeLabelDetail<T extends LabelDetail>(detail: T, changed: LabelDetail): T {
  if (detail.transaction_id !== changed.transaction_id) return detail
  return {
    ...detail,
    automatic_labels: changed.automatic_labels,
    manual_label_decisions: changed.manual_label_decisions,
    effective_labels: changed.effective_labels,
  }
}

export function useLabelOptions() {
  const [options, setOptions] = useState<LabelOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    fetch('/api/pft/review/labels', { signal: controller.signal })
      .then(response => response.ok ? response.json() : Promise.reject())
      .then(data => {
        const labels = Array.isArray(data.labels) ? data.labels : []
        setOptions(labels.filter((option: unknown): option is LabelOption => {
          if (!option || typeof option !== 'object') return false
          const candidate = option as Partial<LabelOption>
          return typeof candidate.value === 'string' && typeof candidate.label === 'string'
        }))
      })
      .catch(caught => {
        if (caught instanceof DOMException && caught.name === 'AbortError') return
        setError('Label options could not be loaded.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [revision])

  return { options, loading, error, retry: () => setRevision(value => value + 1) }
}

function fallbackLabel(value: string) {
  return value.replace(/_/g, ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase())
}

export default function LabelEditor({
  detail,
  options,
  optionsLoading = false,
  optionsError = '',
  disabled = false,
  onRetryOptions,
  onChanged,
}: {
  detail: LabelDetail
  options: LabelOption[]
  optionsLoading?: boolean
  optionsError?: string
  disabled?: boolean
  onRetryOptions?: () => void
  onChanged: (detail: LabelDetail) => void
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const controller = useRef<AbortController | null>(null)
  const panelId = `label-editor-${detail.transaction_id.replace(/[^A-Za-z0-9_-]/g, '-')}`
  const optionMap = useMemo(() => new Map(options.map(option => [option.value, option.label])), [options])
  const sortedOptions = useMemo(
    () => [...options].sort((left, right) => left.label.localeCompare(right.label)),
    [options],
  )
  const excludedCount = Object.values(detail.manual_label_decisions)
    .filter(decision => decision === 'exclude').length
  const unknownLabels = Array.from(new Set([
    ...detail.effective_labels,
    ...Object.keys(detail.manual_label_decisions),
  ])).filter(label => !optionMap.has(label)).sort()

  useEffect(() => () => controller.current?.abort(), [])

  const update = useCallback(async (label: string, choice: LabelChoice) => {
    if (choice === labelChoice(detail, label) || busy || disabled) return
    const request = new AbortController()
    controller.current = request
    setBusy(true)
    setError('')
    setStatus(`Saving ${optionMap.get(label) || fallbackLabel(label)} label…`)
    try {
      const response = await fetch(
        `/api/pft/review/transactions/${encodeURIComponent(detail.transaction_id)}/labels/${encodeURIComponent(label)}`,
        { ...labelMutationRequest(choice), signal: request.signal },
      )
      if (!response.ok) throw new Error('Label change could not be saved.')
      const changed = await response.json() as LabelDetail
      if (request.signal.aborted) return
      onChanged(changed)
      setStatus(`${optionMap.get(label) || fallbackLabel(label)} label saved.`)
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') return
      setError(caught instanceof Error ? caught.message : 'Label change failed.')
      setStatus('')
    } finally {
      if (!request.signal.aborted) setBusy(false)
    }
  }, [busy, detail, disabled, onChanged, optionMap])

  return <div className="mt-3 w-full text-sm">
    <div className="flex flex-wrap items-center gap-2">
      {detail.effective_labels.map(label => {
        const manual = detail.manual_label_decisions[label] === 'include'
        const source = manual ? 'manually included' : 'automatic'
        return <span key={label} title={`${optionMap.get(label) || fallbackLabel(label)} · ${source}`}
          className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium ${
            manual ? 'border-blue-300 bg-blue-50 text-blue-900' : 'border-slate-300 bg-slate-50 text-slate-800'
          }`}>
          {manual ? <Pencil aria-hidden="true" className="h-3 w-3" /> : <Sparkles aria-hidden="true" className="h-3 w-3" />}
          <span>{optionMap.get(label) || fallbackLabel(label)}</span>
          <span className="sr-only">({source})</span>
        </span>
      })}
      {excludedCount > 0 && <span className="text-xs text-muted-foreground">{excludedCount} excluded</span>}
      <button type="button" aria-expanded={open} aria-controls={panelId}
        className="inline-flex items-center gap-1 rounded-md border bg-white px-2.5 py-1 text-xs font-medium hover:bg-slate-50 disabled:opacity-50"
        disabled={busy || disabled} onClick={() => setOpen(value => !value)}>
        Labels <ChevronDown aria-hidden="true" className={`h-3.5 w-3.5 transition ${open ? 'rotate-180' : ''}`} />
      </button>
    </div>

    {open && <div id={panelId} className="mt-2 max-h-72 overflow-y-auto rounded-md border bg-slate-50 p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="font-medium">Labels</p>
        <p className="text-xs text-muted-foreground">Changes save automatically</p>
      </div>
      {optionsLoading && <p className="mt-3 text-xs text-muted-foreground">Loading labels…</p>}
      {optionsError && <p className="mt-3 text-xs text-red-700">
        {optionsError}{' '}
        {onRetryOptions && <button type="button" className="underline" onClick={onRetryOptions}>Retry</button>}
      </p>}
      {!optionsLoading && !optionsError && sortedOptions.length === 0 && (
        <p className="mt-3 text-xs text-muted-foreground">No labels are available.</p>
      )}
      <div className="mt-2 divide-y">
        {sortedOptions.map(option => {
          const automatic = detail.automatic_labels.includes(option.value)
          return <label key={option.value} className="flex flex-wrap items-center justify-between gap-3 py-2">
            <span>
              <span className="font-medium">{option.label}</span>
              <span className="ml-2 text-xs text-muted-foreground">Automatic: {automatic ? 'included' : 'not included'}</span>
            </span>
            <select aria-label={`${option.label} label decision`} value={labelChoice(detail, option.value)}
              disabled={busy || disabled} className="rounded-md border bg-white px-2 py-1 text-xs"
              onChange={event => void update(option.value, event.target.value as LabelChoice)}>
              <option value="auto">Auto</option>
              <option value="include">Include</option>
              <option value="exclude">Exclude</option>
            </select>
          </label>
        })}
        {unknownLabels.map(label => <div key={label} className="flex items-center justify-between gap-3 py-2">
          <span className="font-medium">{fallbackLabel(label)}</span>
          <span className="text-xs text-muted-foreground">Unavailable · read only</span>
        </div>)}
      </div>
      <div className="mt-2 flex items-center justify-between gap-3">
        <span aria-live="polite" className="text-xs text-muted-foreground">{status}</span>
        <button type="button" className="text-xs font-medium text-blue-700 underline" disabled={busy || disabled}
          onClick={() => setOpen(false)}>Done</button>
      </div>
      {error && <p role="alert" className="mt-2 text-xs text-red-700">{error}</p>}
    </div>}
  </div>
}
