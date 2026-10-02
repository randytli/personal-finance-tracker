/** @jest-environment jsdom */
import { createElement } from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import InstitutionItemPage from './page'

jest.mock('next/navigation', () => ({ useParams: () => ({ item_id: 'ally-item' }) }))

const originalFetch = global.fetch
type Request = { path: string; method: string; body: unknown }
let requests: Request[]
let status: string
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
      sync_enabled: status !== 'deactivated', published: status !== 'pending',
      activated_at: null, deactivated_at: null, has_cursor: true, sync_paused: false,
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
    else if (url.pathname.endsWith('/activate') && method === 'POST') { status = 'active'; data = { status } }
    else if (url.pathname.endsWith('/deactivate') && method === 'POST') { status = 'deactivated'; data = { status } }
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
