/** @jest-environment jsdom */
import { createElement } from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import ReviewPage from './page'

jest.mock('@/components/label-editor', () => ({
  __esModule: true, default: () => null,
  useLabelOptions: () => ({ options: [], loading: false, error: null, retry: jest.fn() }),
}))
jest.mock('@/components/bulk-transaction-editor', () => ({ __esModule: true, default: () => null }))

const originalFetch = global.fetch
type Row = ReturnType<typeof row>
function row(id: string, amount: string, type: string, internal = false) {
  return {
    transaction_id: id, transaction_date: '2026-08-12', institution_name: 'Chase',
    account_name: 'Premier Plus Checking', account_mask: '1106', account_type: 'depository',
    merchant_name: id, description: id, amount, plaid_category: 'TRANSFER_OUT',
    original_category: 'TRANSFER_OUT', override_category: null,
    effective_category: 'UNCATEGORIZED', category_editable: type === 'reimbursement',
    automatic_transaction_type: type, effective_transaction_type: type,
    override_transaction_type: null, effective_is_internal_transfer: internal,
  }
}

let rows: Row[]
const requests: URL[] = []
beforeEach(() => {
  requests.length = 0
  rows = [row('friend-credit', '20.49', 'transfer'),
    row('card-payment', '5.00', 'payment', true),
    row('friend-outgoing', '-12.00', 'transfer')]
  global.fetch = jest.fn(async (input, init) => {
    const url = new URL(String(input), 'http://synthetic.test')
    requests.push(url)
    let data: unknown
    if (url.pathname.endsWith('/review/labels')) data = { labels: [] }
    else if (url.pathname.endsWith('/review/categories')) data = { categories: [
      { value: 'UNCATEGORIZED', label: 'Uncategorized' },
      { value: 'FOOD_AND_DRINK', label: 'Food and Drink' },
    ] }
    else if (url.pathname.endsWith('/review/transactions')) {
      const mode = url.searchParams.get('mode')
      const direction = url.searchParams.get('direction')
      const type = url.searchParams.get('transaction_type')
      const matches = mode === 'needs_review' ? [] : rows.filter(item => {
        const incoming = Number(item.amount) > 0
        return (direction === 'all' || (direction === 'incoming') === incoming)
          && (type === 'all' || type === item.effective_transaction_type)
          && (incoming || ['transfer', 'payment', 'unclassified'].includes(item.effective_transaction_type))
      })
      data = { total: matches.length, transactions: matches.slice(Number(url.searchParams.get('offset')),
        Number(url.searchParams.get('offset')) + Number(url.searchParams.get('limit'))) }
    } else if (url.pathname.endsWith('/override') && init?.method === 'PUT') {
      const id = url.pathname.split('/').at(-2)!
      const value = JSON.parse(String(init.body)).transaction_type
      rows = rows.map(item => item.transaction_id === id
        ? { ...item, effective_transaction_type: value, override_transaction_type: value,
          category_editable: value === 'reimbursement' } : item)
      data = { transaction_id: id, effective_transaction_type: value }
    } else if (url.pathname.endsWith('/override') && init?.method === 'DELETE') {
      const id = url.pathname.split('/').at(-2)!
      rows = rows.map(item => item.transaction_id === id
        ? { ...item, effective_transaction_type: item.automatic_transaction_type,
          override_transaction_type: null, category_editable: false } : item)
      data = { transaction_id: id }
    } else throw new Error(`Unexpected request: ${url.pathname}`)
    return { ok: true, json: async () => data } as Response
  }) as typeof fetch
})
afterEach(() => { cleanup(); global.fetch = originalFetch })

test('Credits & Transfers defaults incoming, supports outgoing expense, and protects confirmed internal transfers', async () => {
  render(createElement(ReviewPage))
  await screen.findByText('Nothing needs review.')
  fireEvent.click(screen.getByRole('button', { name: 'Credits & Transfers' }))
  await screen.findByRole('heading', { name: 'friend-credit' })
  expect((screen.getByRole('combobox', { name: 'Direction filter' }) as HTMLSelectElement).value).toBe('incoming')
  expect(screen.queryByRole('heading', { name: 'friend-outgoing' })).toBeNull()
  const payment = screen.getByRole('heading', { name: 'card-payment' }).closest('article')!
  expect(within(payment).getByText(/Confirmed internal transfer/)).toBeTruthy()
  expect((within(payment).getByRole('combobox', { name: /Classification/ }) as HTMLSelectElement).disabled).toBe(true)
  expect((within(payment).getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true)

  fireEvent.change(screen.getByRole('combobox', { name: 'Direction filter' }), { target: { value: 'outgoing' } })
  await screen.findByRole('heading', { name: 'friend-outgoing' })
  expect(screen.queryByRole('heading', { name: 'friend-credit' })).toBeNull()
  const outgoing = screen.getByRole('heading', { name: 'friend-outgoing' }).closest('article')!
  fireEvent.change(within(outgoing).getByRole('combobox', { name: /Classification/ }),
    { target: { value: 'expense' } })
  fireEvent.click(within(outgoing).getByRole('button', { name: 'Save' }))
  await screen.findByText('No matching credits or transfers.')
  expect(rows.find(item => item.transaction_id === 'friend-outgoing')!.effective_transaction_type).toBe('expense')

  fireEvent.change(screen.getByRole('combobox', { name: 'Direction filter' }), { target: { value: 'incoming' } })
  await screen.findByRole('heading', { name: 'friend-credit' })
  const incoming = screen.getByRole('heading', { name: 'friend-credit' }).closest('article')!
  fireEvent.change(within(incoming).getByRole('combobox', { name: /Classification/ }),
    { target: { value: 'reimbursement' } })
  fireEvent.click(within(incoming).getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(rows.find(item => item.transaction_id === 'friend-credit')!.effective_transaction_type).toBe('reimbursement'))
  await screen.findByText(/Effective type: reimbursement/)
  const reimbursed = screen.getByRole('heading', { name: 'friend-credit' }).closest('article')!
  fireEvent.click(within(reimbursed).getAllByRole('button').find(button => button.textContent === 'Uncategorized')!)
  expect(screen.getByText('Spending category')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Undo / Restore automatic' }))
  await waitFor(() => expect(rows.find(item => item.transaction_id === 'friend-credit')!.effective_transaction_type).toBe('transfer'))
  expect(requests.some(url => url.searchParams.get('direction') === 'outgoing')).toBe(true)
})
