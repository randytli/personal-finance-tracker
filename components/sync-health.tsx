'use client'

import { apiFetch } from '@/lib/api'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'

export type SyncStatus = {
  last_published_run_id: string | null
  published_at: string | null
  current_run: { status: string; started_at: string; error_category: string | null } | null
  jobs: { status: 'running' | 'stopped'; heartbeat_at: string | null }
  backup: { status: string; last_success_at: string | null; last_attempt_at: string | null; error_category: string | null }
  institutions: Array<{
    item_id: string; institution_name: string; status: string; sync_paused: boolean
    last_attempt_at: string | null; last_success_at: string | null; last_change_at: string | null
    next_retry_at: string | null
    metadata_warning?: string | null; metadata_warning_at?: string | null
    latest_outcome: { status: string; phase: string; error_category: string | null;
      counts: { added_count: number; modified_count: number; removed_count: number; classified_count: number } } | null
  }>
}

export async function fetchSyncStatus(): Promise<SyncStatus> {
  const response = await apiFetch('/api/pft/sync/status', { cache: 'no-store' })
  if (!response.ok) throw new Error('Sync status unavailable')
  return response.json()
}

export function useSyncRefresh() {
  const [status, setStatus] = useState<SyncStatus | null>(null)
  const [error, setError] = useState(false)
  const [revision, setRevision] = useState(0)
  const marker = useRef<string | null | undefined>(undefined)
  const sequence = useRef(0)

  const check = useCallback(async (refreshOnFocus = false) => {
    // Focus invalidation must survive overlapping status requests and failures.
    if (refreshOnFocus) setRevision(value => value + 1)
    const request = ++sequence.current
    try {
      const next = await fetchSyncStatus()
      if (request === sequence.current) {
        const changed = marker.current !== undefined && marker.current !== next.last_published_run_id
        marker.current = next.last_published_run_id
        setStatus(next)
        setError(false)
        if (changed) setRevision(value => value + 1)
      }
      return next
    } catch (caught) {
      if (request === sequence.current) setError(true)
      throw caught
    }
  }, [])

  useEffect(() => {
    void check().catch(() => undefined)
    const interval = window.setInterval(() => {
      void check().catch(() => undefined)
    }, 45_000)
    const onFocus = () => { if (!document.hidden) void check(true).catch(() => undefined) }
    const onVisibility = () => { if (!document.hidden) void check(true).catch(() => undefined) }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      sequence.current++
      window.clearInterval(interval)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [check])

  return { status, error, revision, invalidate: () => setRevision(value => value + 1), check }
}

// Read the marker around the whole response batch. A publication crossing the
// requests forces a retry, while page effects reject responses from older loads.
export async function consistentJson(paths: string[], check: () => Promise<SyncStatus>) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const before = await check()
    const responses = await Promise.all(paths.map(path => apiFetch(path, { cache: 'no-store' })))
    if (responses.some(response => !response.ok)) throw new Error('Query failed')
    const data = await Promise.all(responses.map(response => response.json()))
    const after = await check()
    if (before.last_published_run_id === after.last_published_run_id) return data
  }
  throw new Error('Sync changed during refresh')
}

function time(value: string | null) {
  return value ? new Date(value).toLocaleString() : 'Never'
}

export function SyncHealth({ status, error, onRetry }: { status: SyncStatus | null; error: boolean; onRetry?: () => void }) {
  const warnings = status ? [
    !status.published_at && 'No published sync yet',
    status.current_run?.status === 'partial' && 'Latest run: partial',
    status.current_run?.error_category && `Run error: ${status.current_run.error_category}`,
    (status.current_run?.status === 'failed' || status.current_run?.status === 'error')
      && !status.current_run.error_category && `Latest run: ${status.current_run.status}`,
    status.jobs.status === 'stopped' && 'Jobs stopped',
    status.backup.status !== 'healthy' && `Backup: ${status.backup.status}${status.backup.error_category ? ` (${status.backup.error_category})` : ''}`,
    ...status.institutions.flatMap(item => [
      item.status === 'active' && !item.last_success_at && `${item.institution_name}: no successful bank check`,
      (item.status !== 'active' || item.sync_paused) && `${item.institution_name}: ${item.status}${item.sync_paused ? ', paused' : ''}`,
      item.metadata_warning && `${item.institution_name}: ${item.metadata_warning}`,
      item.latest_outcome?.error_category && `${item.institution_name}: ${item.latest_outcome.error_category}`,
      (item.latest_outcome?.status === 'failed' || item.latest_outcome?.status === 'error')
        && !item.latest_outcome.error_category && `${item.institution_name}: ${item.latest_outcome.status}`,
    ]),
  ].filter((warning): warning is string => Boolean(warning)) : []

  const tone = error ? 'bg-destructive' : !status ? 'bg-muted-foreground/40 animate-pulse' : warnings.length ? 'bg-warning' : 'bg-success'
  return <section aria-label="Sync and backup health" className="overflow-hidden break-words rounded-xl border bg-card text-sm shadow-[0_1px_2px_rgb(15_23_42/0.04)] [overflow-wrap:anywhere]">
    <details className="group px-4 py-2.5">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-2 gap-y-0.5 rounded-md font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className={cn('size-2 shrink-0 rounded-full', tone)} />
        <span>Sync and backup health</span>
        {warnings.length > 0 && <span className="rounded-full bg-warning-soft px-2 py-0.5 text-xs font-medium text-warning ring-1 ring-inset ring-warning/25">
          {warnings.length} {warnings.length === 1 ? 'warning' : 'warnings'}
        </span>}
        <ChevronDown aria-hidden="true" className="ml-auto size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180 sm:order-last" />
        <span className="basis-full pl-4 text-xs font-normal text-muted-foreground sm:basis-auto sm:pl-0 sm:text-sm">
          {status ? `· Last published ${time(status.published_at)}` : '· Checking status…'}
        </span>
        {!error && status && warnings.length === 0 && <span className="font-normal text-success">· All clear</span>}
      </summary>
      {status && <div className="mt-2.5 border-t pt-2.5 text-[13px]">
        <p className="mb-2 text-xs text-muted-foreground">{error ? 'Last reported status. API reachability could not be verified.' : 'API reachable. Bank freshness is shown separately for each institution.'}</p>
        <p>Latest run: {status.current_run?.status || 'None'}</p>
        <p>Jobs: {status.jobs.status} · Last heartbeat: {time(status.jobs.heartbeat_at)}</p>
        <p>Backup: {status.backup.status} · Last successful: {time(status.backup.last_success_at)}</p>
        <ul className="mt-2 flex flex-col gap-1">
        {status.institutions.map(item => <li key={item.item_id} className="border-t pt-2">
          <details>
          <summary className="cursor-pointer rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <strong className="font-medium">{item.institution_name}</strong> ({item.status}{item.sync_paused ? ', paused' : ''})
          <span className="block text-xs text-muted-foreground">Last bank check: {time(item.last_success_at)}</span>
          </summary>
          <div className="py-2 text-xs text-muted-foreground">
          Last attempt: {time(item.last_attempt_at)}
          {' · '}Last change: {time(item.last_change_at)}
          {item.metadata_warning && <span className="text-warning">
            {' · '}Metadata warning: {item.metadata_warning} ({time(item.metadata_warning_at || null)})
          </span>}
          {item.latest_outcome && <> · {item.latest_outcome.status}
            {item.latest_outcome.error_category && <span className="text-warning">
              {' · '}{item.latest_outcome.phase}: {item.latest_outcome.error_category}
            </span>}
            {' · '}Added {item.latest_outcome.counts.added_count}, modified {item.latest_outcome.counts.modified_count}, removed {item.latest_outcome.counts.removed_count}
          </>}
          {item.next_retry_at && <> · Retry: {time(item.next_retry_at)}</>}
          </div>
          </details>
        </li>)}
        </ul>
      </div>}
    </details>
    {error && <p role="alert" className="border-t bg-destructive/5 px-4 py-2.5 text-destructive">Status unavailable. {status ? 'Last reported values are shown; bank freshness could not be verified.' : 'Bank freshness could not be verified.'}
      {onRetry && <button type="button" className="ml-2 rounded-md px-2 font-medium underline underline-offset-4" onClick={onRetry}>Retry status</button>}
    </p>}
    {warnings.length > 0 && <ul tabIndex={0} className="flex max-h-32 flex-col gap-1 overflow-y-auto overscroll-contain border-t bg-warning-soft/50 px-4 py-2.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring" aria-label="Sync and backup warnings">
      {warnings.map((warning, index) => <li key={`${warning}-${index}`} className="flex gap-2">
        <TriangleAlert aria-hidden="true" className="mt-px size-3.5 shrink-0 text-warning" /><span className="min-w-0">{warning}</span>
      </li>)}
    </ul>}
  </section>
}
