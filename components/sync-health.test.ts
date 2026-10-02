/** @jest-environment jsdom */
import { createElement } from 'react'
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { consistentJson, SyncHealth, useSyncRefresh, type SyncStatus } from './sync-health'

const originalFetch = global.fetch
const status = (id: string | null): SyncStatus => ({ last_published_run_id: id, published_at: null,
  current_run: null, jobs: { status: 'stopped', heartbeat_at: null },
  backup: { status: 'never', last_success_at: null, last_attempt_at: null, error_category: null },
  institutions: [] })
const response = (value: unknown) => ({ ok: true, json: async () => value } as Response)

afterEach(() => { cleanup(); global.fetch = originalFetch; jest.useRealTimers() })

test('health details start collapsed while warnings remain visible', () => {
  const healthy: SyncStatus = {
    last_published_run_id: 'test', published_at: '2026-09-28T12:00:00Z', current_run: null,
    jobs: { status: 'running', heartbeat_at: null },
    backup: { status: 'healthy', last_success_at: null, last_attempt_at: null, error_category: null },
    institutions: [],
  }
  const view = render(createElement(SyncHealth, { status: healthy, error: false }))
  const summary = screen.getByText('Sync and backup health')
  expect(summary.closest('details')?.open).toBe(false)
  expect(screen.getByText('· All clear')).toBeTruthy()
  view.rerender(createElement(SyncHealth, { status: {
    ...healthy, jobs: { status: 'stopped', heartbeat_at: null },
    backup: { ...healthy.backup, status: 'failed', error_category: 'backup-error' },
  }, error: false }))
  expect(summary.closest('details')?.open).toBe(false)
  const warnings = screen.getByRole('list', { name: 'Sync and backup warnings' })
  expect(within(warnings).getByText('Jobs stopped')).toBeTruthy()
  expect(within(warnings).getByText('Backup: failed (backup-error)')).toBeTruthy()
})

test('45-second polling and focus refresh, including unchanged publication', async () => {
  jest.useFakeTimers()
  let marker = 'published-one'
  const requests: string[] = []
  global.fetch = jest.fn(async input => {
    requests.push(String(input))
    return response(status(marker))
  }) as typeof fetch
  const { result } = renderHook(() => useSyncRefresh())
  await act(async () => { await Promise.resolve() })
  expect(result.current.revision).toBe(0)
  await act(async () => { jest.advanceTimersByTime(45_000); await Promise.resolve() })
  expect(requests).toHaveLength(2)
  expect(result.current.revision).toBe(0)
  marker = 'partial-or-no-op-publication'
  await act(async () => { jest.advanceTimersByTime(45_000); await Promise.resolve() })
  expect(result.current.revision).toBe(1)
  await act(async () => { window.dispatchEvent(new Event('focus')); await Promise.resolve() })
  expect(result.current.revision).toBe(2)
})

test('crossing publication retries the complete response batch', async () => {
  const markers = ['first', 'second', 'second', 'second']
  let query = 0
  global.fetch = jest.fn(async input => String(input).endsWith('/sync/status')
    ? response(status(markers.shift()!)) : response({ query: ++query })) as typeof fetch
  const check = async () => {
    const value = await global.fetch('/api/pft/sync/status')
    return value.json()
  }
  const [data] = await consistentJson(['/analytics'], check)
  expect(query).toBe(2)
  expect(data.query).toBe(2)
})

test('focus invalidation survives an overlapping unchanged-marker status check', async () => {
  let release!: (value: Response) => void
  global.fetch = jest.fn(async () => response(status('same'))) as typeof fetch
  const { result } = renderHook(() => useSyncRefresh())
  await waitFor(() => expect(result.current.status?.last_published_run_id).toBe('same'))
  global.fetch = jest.fn(() => new Promise<Response>(resolve => { release = resolve })) as typeof fetch
  let focus!: Promise<unknown>
  act(() => { focus = result.current.check(true) })
  expect(result.current.revision).toBe(1)
  global.fetch = jest.fn(async () => response(status('same'))) as typeof fetch
  await act(async () => { await result.current.check() })
  await act(async () => { release(response(status('same'))); await focus })
  expect(result.current.revision).toBe(1)
})

test('late status response cannot restore an older marker', async () => {
  let release!: (value: Response) => void
  let calls = 0
  global.fetch = jest.fn(() => {
    calls++
    return calls === 2 ? new Promise<Response>(resolve => { release = resolve })
      : Promise.resolve(response(status(calls === 1 ? 'old' : 'new')))
  }) as typeof fetch
  const { result } = renderHook(() => useSyncRefresh())
  await waitFor(() => expect(result.current.status?.last_published_run_id).toBe('old'))
  act(() => { window.dispatchEvent(new Event('focus')) })
  await act(async () => { window.dispatchEvent(new Event('focus')); await Promise.resolve() })
  expect(result.current.status?.last_published_run_id).toBe('new')
  await act(async () => { release(response(status('old'))); await Promise.resolve() })
  expect(result.current.status?.last_published_run_id).toBe('new')
})

test('API failure keeps last reported bank freshness, suppresses all-clear, and permits retry', () => {
  const onRetry = jest.fn()
  const last: SyncStatus = { ...status('old'), published_at: '2026-09-01T12:00:00Z',
    jobs: { status: 'running', heartbeat_at: null },
    backup: { status: 'healthy', last_success_at: null, last_attempt_at: null, error_category: null } }
  render(createElement(SyncHealth, { status: last, error: true, onRetry }))
  expect(screen.queryByText('· All clear')).toBeNull()
  expect(screen.getByRole('alert').textContent).toContain('Last reported values are shown')
  expect(screen.getByText(/Last reported status/)).toBeTruthy()
  screen.getByRole('button', { name: 'Retry status' }).click()
  expect(onRetry).toHaveBeenCalledTimes(1)
})

test('never-published, partial, paused, failed-bank, and metadata warnings stay visible when details collapse', () => {
  const value: SyncStatus = { ...status(null),
    current_run: { status: 'partial', started_at: '2026-09-01T12:00:00Z', error_category: null },
    institutions: [{ item_id: 'synthetic', institution_name: 'Synthetic Bank', status: 'active', sync_paused: true,
      last_attempt_at: '2026-09-01T12:00:00Z', last_success_at: null, last_change_at: null, next_retry_at: null,
      metadata_warning: 'account-metadata-stale', latest_outcome: { status: 'failed', phase: 'fetch',
        error_category: 'connection-error', counts: { added_count: 0, modified_count: 0, removed_count: 0, classified_count: 0 } } }] }
  render(createElement(SyncHealth, { status: value, error: false }))
  const warnings = screen.getByRole('list', { name: 'Sync and backup warnings' })
  for (const text of ['No published sync yet', 'Latest run: partial', 'Synthetic Bank: no successful bank check',
    'Synthetic Bank: active, paused', 'Synthetic Bank: account-metadata-stale', 'Synthetic Bank: connection-error']) {
    expect(within(warnings).getByText(text)).toBeTruthy()
  }
  expect(screen.queryByText('· All clear')).toBeNull()
  expect(screen.getByText(/Last bank check: Never/)).toBeTruthy()
})

test('each institution links to its management page', () => {
  render(createElement(SyncHealth, { status: { ...status('published'), institutions: [{
    item_id: 'item/with space', institution_name: 'Ally Bank', status: 'pending', sync_paused: false,
    last_attempt_at: null, last_success_at: null, last_change_at: null, next_retry_at: null, latest_outcome: null,
  }] }, error: false }))
  // Visible as soon as the health panel opens, without expanding the institution row.
  const panel = screen.getByText('Sync and backup health').closest('details') as HTMLDetailsElement
  expect(panel.open).toBe(false)
  fireEvent.click(panel.querySelector('summary')!)
  expect(panel.open).toBe(true)
  const row = screen.getByText('Ally Bank').closest('details') as HTMLDetailsElement
  expect(row.open).toBe(false)
  const link = screen.getByRole('link', { name: 'Manage Ally Bank' })
  expect(link.getAttribute('href')).toBe('/plaid/items/item%2Fwith%20space')
})
