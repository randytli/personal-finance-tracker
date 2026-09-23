/** @jest-environment jsdom */
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { consistentJson, useSyncRefresh } from './sync-health'

const originalFetch = global.fetch
const status = (id: string | null) => ({ last_published_run_id: id, published_at: null,
  current_run: null, jobs: { status: 'stopped', heartbeat_at: null },
  backup: { status: 'never', last_success_at: null, last_attempt_at: null, error_category: null },
  institutions: [] })
const response = (value: unknown) => ({ ok: true, json: async () => value } as Response)

afterEach(() => { cleanup(); global.fetch = originalFetch; jest.useRealTimers() })

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
