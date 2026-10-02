/** @jest-environment jsdom */
import { createElement } from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import InstitutionItemPage from './page'

jest.mock('next/navigation', () => ({ useParams: () => ({ item_id: 'ally-item' }) }))

const originalFetch = global.fetch
type Request = { path: string; method: string; body: unknown }
let requests: Request[]
let status: string
let disconnectedAt: string | null
let checks: Array<{ id: string; label: string; result: string; detail: string }>

const classification = (type: string, internal: boolean) =>
  ({ transaction_type: type, is_spending: false, is_internal_transfer: internal, category: 'UNCATEGORIZED' })

const activationPreview = {
  item_id: 'ally-item', transition: 'activate', digest: 'a'.repeat(64),
  summary_by_month: [{ month: '2026-08', metrics: { income: { before: '2050.00', after: '2000.00', delta: '-50.00' } }, categories: [] }],
  new_transactions: [{ transaction_id: 'b-zelle-out' }],
  removed_transactions: [],
  changed_existing_transactions: [{
    transaction_id: 'a-zelle-in', item_id: 'chase', institution_name: 'Chase', account_name: 'Checking',
    transaction_date: '2026-08-04', month: '2026-08', amount: '50', merchant_name: null,
    description: 'ZELLE PAYMENT FROM SAM', manual_type: false,
    before: classification('income', false), after: classification('transfer', true),
  }],
}

beforeEach(() => {
  requests = []
  status = 'pending'
  disconnectedAt = null
  checks = [{ id: 'K1', label: 'Item can be activated', result: 'pass', detail: 'Status is pending' },
    { id: 'K8', label: 'Sync health', result: 'warn', detail: 'metadata warning' }]
  window.matchMedia = jest.fn(() => ({ matches: false, addEventListener: jest.fn(), removeEventListener: jest.fn() })) as unknown as typeof window.matchMedia
  global.fetch = jest.fn(async (input, init) => {
    const url = new URL(String(input), 'http://synthetic.test')
    const method = init?.method || 'GET'
    requests.push({ path: url.pathname, method, body: init?.body ? JSON.parse(String(init.body)) : null })
    let data: unknown
    if (url.pathname === '/api/pft/plaid/items/ally-item') data = {
      item_id: 'ally-item', institution_name: 'Ally', status,
      // Mirrors the generated columns: sync_enabled = active; published = active or deactivated.
      sync_enabled: status === 'active', published: status === 'active' || status === 'deactivated',
      activated_at: null, deactivated_at: null, has_cursor: true, sync_paused: false,
      disconnected_at: disconnectedAt,
      last_sync_success_at: null, metadata_warning: null, raw_transaction_count: 2, normalized_transaction_count: 2,
      accounts: [{ account_id: 'b-check', name: 'Ally Checking', mask: '0001', type: 'depository', subtype: 'checking',
        consumer_transactions_enabled: true, transaction_count: 2 }],
    }
    else if (url.pathname.endsWith('/transactions-preview')) data = { total: 1, transactions: [{
      transaction_id: 'b-zelle-out', account_name: 'Ally Checking', transaction_date: '2026-08-04', amount: '-50',
      merchant_name: null, description: 'ZELLE PAYMENT TO RANDY', plaid_category: 'TRANSFER_OUT', transaction_type: null }] }
    else if (url.pathname.endsWith('/activation-checks')) data = { checks }
    else if (url.pathname.endsWith('/activation-preview') && method === 'POST') data = activationPreview
    else if (url.pathname.endsWith('/deactivation-preview') && method === 'POST') data = {
      ...activationPreview, digest: 'd'.repeat(64), summary_by_month: [], new_transactions: [], changed_existing_transactions: [] }
    else if (url.pathname.endsWith('/reactivation-preview') && method === 'POST') data = {
      ...activationPreview, digest: 'r'.repeat(64), summary_by_month: [], new_transactions: [], changed_existing_transactions: [] }
    else if (url.pathname.endsWith('/activate') && method === 'POST') { status = 'active'; data = { status } }
    else if (url.pathname.endsWith('/reactivate') && method === 'POST') { status = 'active'; data = { status } }
    else if (url.pathname.endsWith('/disconnect') && method === 'POST') { disconnectedAt = '2026-10-02T18:00:00Z'; data = { status } }
    else if (url.pathname.endsWith('/reject') && method === 'POST') { status = 'disabled'; data = { status } }
    else if (url.pathname.endsWith('/retry-onboarding') && method === 'POST') { status = 'pending'; data = { status } }
    else if (url.pathname.endsWith('/deactivate') && method === 'POST') {
      status = 'deactivated'
      if ((init?.body && JSON.parse(String(init.body)).disconnect) === true) disconnectedAt = '2026-10-02T18:00:00Z'
      data = { status }
    }
    else throw new Error(`Unexpected request: ${method} ${url.pathname}`)
    return { ok: true, json: async () => data } as Response
  }) as typeof fetch
})

afterEach(() => { cleanup(); global.fetch = originalFetch })

const writes = () => requests.filter(request => request.method === 'POST')

test('activation previews the whole ledger and commits only after manual confirmation', async () => {
  render(createElement(InstitutionItemPage))
  await screen.findByRole('heading', { name: 'Ally' })
  await screen.findByText('Item can be activated')
  expect(screen.getByRole('heading', { name: 'Prepare for review' })).toBeTruthy()
  expect(screen.getByText('ZELLE PAYMENT TO RANDY')).toBeTruthy()
  // Loading the page never previews or activates anything.
  expect(writes()).toEqual([])

  fireEvent.click(screen.getByRole('button', { name: 'Activate' }))
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('Existing transactions that change')
  expect(within(dialog).getByText('ZELLE PAYMENT FROM SAM')).toBeTruthy()
  expect(within(dialog).getByText('2026-08')).toBeTruthy()
  expect(writes().map(request => request.path)).toEqual(['/api/pft/plaid/items/ally-item/activation-preview'])

  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm activation' }))
  await screen.findByText('Institution activated.')
  expect(writes().at(-1)).toEqual({ path: '/api/pft/plaid/items/ally-item/activate', method: 'POST',
    body: { preview_digest: 'a'.repeat(64) } })
  await screen.findByRole('button', { name: 'Deactivate' })
})

test('cancelling the activation dialog writes nothing', async () => {
  render(createElement(InstitutionItemPage))
  fireEvent.click(await screen.findByRole('button', { name: 'Activate' }))
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('Existing transactions that change')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(writes().map(request => request.path)).toEqual(['/api/pft/plaid/items/ally-item/activation-preview'])
})

test('a failed pre-activation check disables activation', async () => {
  checks = [...checks, { id: 'K5', label: 'Initial sync completed', result: 'fail', detail: 'No transactions have been synced' }]
  render(createElement(InstitutionItemPage))
  await screen.findByText('Initial sync completed')
  expect((screen.getByRole('button', { name: 'Activate' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByText(/Activation is unavailable/)).toBeTruthy()
})

test('deactivation shows an unchanged ledger and needs confirmation', async () => {
  status = 'active'
  render(createElement(InstitutionItemPage))
  fireEvent.click(await screen.findByRole('button', { name: 'Deactivate' }))
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText(/No change: analytics and every published classification stay exactly the same/)
  expect(writes().map(request => request.path)).toEqual(['/api/pft/plaid/items/ally-item/deactivation-preview'])
  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm deactivation' }))
  await screen.findByText(/Institution deactivated/)
  expect(writes().at(-1)?.body).toEqual({ preview_digest: 'd'.repeat(64) })
  await screen.findByRole('button', { name: 'Reactivate' })
})

test('reactivation uses its own preview and confirmation', async () => {
  status = 'deactivated'
  render(createElement(InstitutionItemPage))
  await screen.findByText('Item can be activated')
  expect(writes()).toEqual([])
  fireEvent.click(screen.getByRole('button', { name: 'Reactivate' }))
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText(/No change: analytics/)
  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm reactivation' }))
  await screen.findByText('Institution reactivated.')
  expect(writes()).toEqual([
    { path: '/api/pft/plaid/items/ally-item/reactivation-preview', method: 'POST', body: null },
    { path: '/api/pft/plaid/items/ally-item/reactivate', method: 'POST', body: { preview_digest: 'r'.repeat(64) } },
  ])
})

const STAGED = 'While Rejected, data already staged for this institution stays unpublished: it is not in scheduled sync and not in analytics.'

test('cancel onboarding rejects only after a second confirmation', async () => {
  render(createElement(InstitutionItemPage))
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel onboarding' }))
  let dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByText(STAGED)).toBeTruthy()
  fireEvent.click(within(dialog).getByRole('button', { name: 'Keep current status' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(writes()).toEqual([])

  fireEvent.click(screen.getByRole('button', { name: 'Cancel onboarding' }))
  dialog = await screen.findByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm cancel onboarding' }))
  await screen.findByText(/Onboarding cancelled/)
  expect(writes()).toEqual([{ path: '/api/pft/plaid/items/ally-item/reject', method: 'POST', body: null }])
  await screen.findByRole('button', { name: 'Retry onboarding' })
  expect(screen.queryByRole('button', { name: 'Activate' })).toBeNull()
})

test('a rejected institution offers only retry onboarding, which changes nothing but status', async () => {
  status = 'disabled'
  render(createElement(InstitutionItemPage))
  await screen.findByText(/Rejected institutions cannot be activated/)
  expect(screen.queryByRole('button', { name: /activate|deactivate|cancel onboarding/i })).toBeNull()
  expect(requests.some(request => request.path.endsWith('/activation-checks'))).toBe(false)
  expect(writes()).toEqual([])

  fireEvent.click(screen.getByRole('button', { name: 'Retry onboarding' }))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByText(STAGED)).toBeTruthy()
  expect(within(dialog).getByText('It does not import transactions, normalize, publish or activate anything.')).toBeTruthy()
  expect(writes()).toEqual([])
  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm retry onboarding' }))
  await screen.findByText(/Onboarding retried/)
  // Exactly one write: no import, normalization, preview or activation follows.
  expect(writes()).toEqual([{ path: '/api/pft/plaid/items/ally-item/retry-onboarding', method: 'POST', body: null }])
  await screen.findByRole('button', { name: 'Activate' })
  await screen.findByText('Item can be activated')
  expect(writes()).toHaveLength(1)
})

const RECONNECT = 'Reactivating a disconnected institution requires reconnecting it through Plaid Link; until reconnecting is supported, it cannot be reactivated.'

test('plain deactivation keeps the Plaid connection; disconnecting is a separate confirmed option', async () => {
  status = 'active'
  render(createElement(InstitutionItemPage))
  fireEvent.click(await screen.findByRole('button', { name: 'Deactivate and disconnect' }))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByText(RECONNECT)).toBeTruthy()
  await within(dialog).findByText(/No change: analytics/)
  expect(writes().map(request => request.path)).toEqual(['/api/pft/plaid/items/ally-item/deactivation-preview'])
  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm deactivate and disconnect' }))
  await screen.findByText(/deactivated and disconnected from Plaid/)
  expect(writes().at(-1)).toEqual({ path: '/api/pft/plaid/items/ally-item/deactivate', method: 'POST',
    body: { preview_digest: 'd'.repeat(64), disconnect: true } })
  // Disconnected: reactivation is blocked and says why.
  await screen.findByText(/Disconnected from Plaid on 2026-10-02/)
  expect(screen.queryByRole('button', { name: 'Disconnect from Plaid' })).toBeNull()
})

test('a disconnected institution cannot be reactivated from the page', async () => {
  status = 'deactivated'
  disconnectedAt = '2026-10-01T12:00:00Z'
  checks = [...checks, { id: 'K13', label: 'Plaid connection', result: 'fail',
    detail: 'Disconnected from Plaid; reactivation requires reconnecting through Plaid Link' }]
  render(createElement(InstitutionItemPage))
  await screen.findByText('Plaid connection')
  expect((screen.getByRole('button', { name: 'Reactivate' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByText(/Disconnected from Plaid on 2026-10-01/).textContent).toContain(RECONNECT)
  expect(writes()).toEqual([])
})

test('a deactivated, still-connected institution can be disconnected after confirmation', async () => {
  status = 'deactivated'
  render(createElement(InstitutionItemPage))
  fireEvent.click(await screen.findByRole('button', { name: 'Disconnect from Plaid' }))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByText(RECONNECT)).toBeTruthy()
  expect(writes()).toEqual([])
  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm disconnect' }))
  await screen.findByText(/Disconnected from Plaid. The institution stays deactivated/)
  expect(writes()).toEqual([{ path: '/api/pft/plaid/items/ally-item/disconnect', method: 'POST', body: null }])
})
