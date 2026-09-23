'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

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
  const response = await fetch('/api/pft/sync/status', { cache: 'no-store' })
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
    const responses = await Promise.all(paths.map(path => fetch(path, { cache: 'no-store' })))
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

export function SyncHealth({ status, error }: { status: SyncStatus | null; error: boolean }) {
  return <section aria-label="Sync and backup health" className="rounded-lg border bg-white p-4 text-sm shadow-sm">
    <h2 className="font-semibold">Sync and backup health</h2>
    {error && <p role="alert" className="mt-2 text-red-700">Status unavailable. Check the local API.</p>}
    {status && <>
      <p className="mt-2">Last published: {time(status.published_at)} · Latest run: {status.current_run?.status || 'None'}</p>
      {status.current_run?.error_category && <p className="text-amber-700">Run error: {status.current_run.error_category}</p>}
      <p className={status.jobs.status === 'stopped' ? 'text-red-700' : ''}>
        Jobs: {status.jobs.status} · Last heartbeat: {time(status.jobs.heartbeat_at)}
      </p>
      <p className={status.backup.status === 'healthy' ? '' : 'text-amber-700'}>
        Backup: {status.backup.status} · Last successful: {time(status.backup.last_success_at)}
        {status.backup.error_category && ` · ${status.backup.error_category}`}
      </p>
      <ul className="mt-2 space-y-1">
        {status.institutions.map(item => <li key={item.item_id}>
          <strong>{item.institution_name}</strong> ({item.status}{item.sync_paused ? ', paused' : ''})
          {' · '}Last check: {time(item.last_success_at)} · Last attempt: {time(item.last_attempt_at)}
          {' · '}Last change: {time(item.last_change_at)}
          {item.metadata_warning && <span className="text-amber-700">
            {' · '}Metadata warning: {item.metadata_warning} ({time(item.metadata_warning_at || null)})
          </span>}
          {item.latest_outcome && <> · {item.latest_outcome.status}
            {item.latest_outcome.error_category && <span className="text-amber-700">
              {' · '}{item.latest_outcome.phase}: {item.latest_outcome.error_category}
            </span>}
            {' · '}Added {item.latest_outcome.counts.added_count}, modified {item.latest_outcome.counts.modified_count}, removed {item.latest_outcome.counts.removed_count}
          </>}
          {item.next_retry_at && <> · Retry: {time(item.next_retry_at)}</>}
        </li>)}
      </ul>
    </>}
  </section>
}
