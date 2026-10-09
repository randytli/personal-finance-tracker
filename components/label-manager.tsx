'use client'

import { useId, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetTrigger } from '@/components/ui/sheet'
import { ControlField, fieldClassName } from '@/components/page-presentation'
import type { LabelOption } from '@/components/label-editor'

export const labelColors = [
  { value: '', label: 'Default' }, { value: 'info', label: 'Blue' },
  { value: 'success', label: 'Green' }, { value: 'warning', label: 'Amber' },
  { value: 'muted', label: 'Muted' },
] as const

export default function LabelManager({ options, loading = false, optionsError = '', onRetry }: {
  options: LabelOption[]; loading?: boolean; optionsError?: string; onRetry?: () => void
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [color, setColor] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [archiving, setArchiving] = useState<LabelOption | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')

  function reset() {
    setEditing(null); setName(''); setColor(''); setArchiving(null); setError('')
  }

  async function mutate(path: string, method: string, body?: object) {
    if (busy) return
    setBusy(true); setError(''); setStatus('')
    try {
      const response = await fetch(`/api/pft/review/labels${path}`, {
        method, ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Label could not be saved. Check its name and try again.')
      reset()
      setStatus(method === 'POST' && path.endsWith('/archive') ? 'Label archived. Historical associations are retained.' : 'Label saved.')
      window.dispatchEvent(new Event('pft-label-options-changed'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Label could not be saved.')
    } finally { setBusy(false) }
  }

  return <Sheet open={open} onOpenChange={next => { if (!busy) { setOpen(next); if (!next) reset() } }}>
    <SheetTrigger asChild><Button type="button" variant="outline" size="sm">Manage labels</Button></SheetTrigger>
    <SheetContent className="pft-app flex flex-col gap-5 overflow-y-auto">
      <SheetHeader>
        <SheetTitle>Manage labels</SheetTitle>
        <SheetDescription>Organize transactions without changing their financial classification.</SheetDescription>
      </SheetHeader>
      <form className="flex flex-col gap-3" onSubmit={event => {
        event.preventDefault()
        void mutate(editing ? `/${encodeURIComponent(editing)}` : '', editing ? 'PATCH' : 'POST', { name: name.trim(), color: color || null })
      }}>
        <h3 className="font-semibold">{editing ? 'Rename label' : 'Create label'}</h3>
        <ControlField label="Name">
          <input id={`${id}-name`} aria-label="Label name" className={fieldClassName} required maxLength={80}
            value={name} disabled={busy} onChange={event => setName(event.target.value)} />
        </ControlField>
        <ControlField label="Color (optional)">
          <select aria-label="Label color" value={color} className={fieldClassName} disabled={busy}
            onChange={event => setColor(event.target.value)}>
            {labelColors.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </ControlField>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" size="sm" disabled={busy || !name.trim()}>{busy ? 'Saving…' : editing ? 'Save label' : 'Create label'}</Button>
          {editing && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={reset}>Cancel edit</Button>}
        </div>
      </form>
      {loading && <p role="status" className="text-sm text-muted-foreground">Loading labels…</p>}
      {optionsError && <p role="alert" className="text-sm text-destructive">{optionsError}{' '}
        <Button variant="link" size="inline" onClick={onRetry}>Retry</Button></p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <p role="status" className="text-sm text-muted-foreground">{status}</p>
      <ul className="flex flex-col divide-y" aria-label="Available labels">
        {options.map(option => <li key={option.value} className="flex flex-wrap items-center justify-between gap-3 py-3">
          <div className="min-w-0">
            <Badge variant={option.color || 'outline'}><span className="break-all">{option.label}</span></Badge>
            <p className="mt-1 text-xs text-muted-foreground">{option.is_system ? 'System · automatic rules' : option.archived ? 'Archived · history retained' : 'Custom label'}</p>
          </div>
          {!option.is_system && <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" aria-label={`Rename ${option.label}`} disabled={busy} onClick={() => {
              setEditing(option.value); setName(option.label); setColor(option.color || ''); setError(''); setArchiving(null)
            }}>Rename</Button>
            {!option.archived && <Button size="sm" variant="outline" aria-label={`Archive ${option.label}`} disabled={busy}
              onClick={() => setArchiving(option)}>Archive</Button>}
          </div>}
        </li>)}
      </ul>
      {archiving && <div className="flex flex-col gap-3 rounded-xl border p-3">
        <p className="text-sm">Archive {archiving.label}? Historical associations stay visible. This label will no longer be available for new marking.</p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={busy} onClick={() => void mutate(`/${encodeURIComponent(archiving.value)}/archive`, 'POST')}>Confirm archive</Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => setArchiving(null)}>Cancel archive</Button>
        </div>
      </div>}
    </SheetContent>
  </Sheet>
}
