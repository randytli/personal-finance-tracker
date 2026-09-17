/** @jest-environment jsdom */
import { createElement } from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import HomePage from './page'

jest.mock('recharts', () => ({
  ResponsiveContainer: () => null,
  CartesianGrid: () => null, Legend: () => null, Line: () => null,
  LineChart: () => null, Tooltip: () => null, XAxis: () => null, YAxis: () => null,
}))
jest.mock('@/components/plaid-link-button', () => () => null)
jest.mock('@/components/category-editor', () => ({ __esModule: true, default: () => null }))
jest.mock('@/components/benefit-category-editor', () => ({ __esModule: true, default: () => null }))
jest.mock('@/components/label-editor', () => ({
  __esModule: true, default: () => null,
  useLabelOptions: () => ({ options: [], loading: false, error: null }),
}))

const summary = {
  gross_spending: '100.00', refunds: '10.00', card_benefits: '23.80',
  net_spending: '66.20', income: '0.00', net_savings: '-66.20', unclassified_count: 0,
  category_breakdown: [{ category: 'GENERAL_MERCHANDISE', gross_spending: '100.00',
    refunds: '10.00', expense_transaction_count: 1, refund_transaction_count: 1 }],
  // Deliberately unsorted to verify the client shows largest credits first.
  benefit_category_breakdown: [
    { benefit_category: 'TRANSPORTATION_CREDIT', benefit_amount: '9.99', benefit_transaction_count: 1 },
    { benefit_category: 'SHOPPING_CREDIT', benefit_amount: '13.81', benefit_transaction_count: 1 },
  ],
}
const requests: URL[] = []
const originalFetch = global.fetch

beforeEach(() => {
  requests.length = 0
  global.fetch = jest.fn(async (input) => {
    const url = new URL(String(input), 'http://synthetic.test')
    requests.push(url)
    let data: unknown
    if (url.pathname.endsWith('/monthly')) data = { ...summary, month: url.searchParams.get('month') }
    else if (url.pathname.endsWith('/trend')) data = { months: [] }
    else if (url.pathname.endsWith('/breakdown')) data = { groups: [] }
    else if (url.pathname.endsWith('/benefit-categories')) data = { categories: [
      { value: 'SHOPPING_CREDIT', label: 'Shopping' },
      { value: 'TRANSPORTATION_CREDIT', label: 'Transportation' },
    ] }
    else if (url.pathname.endsWith('/categories')) data = { categories: [] }
    else if (url.pathname.endsWith('/transactions')) {
      const kind = url.searchParams.get('transaction_type')
      data = { total: 1, transactions: [{ transaction_id: 'synthetic',
        transaction_date: `${url.searchParams.get('month')}-12`,
        merchant_name: `Synthetic ${kind}`, description: 'Synthetic credit or purchase',
        transaction_type: kind, amount: kind === 'expense' ? '-100.00' : kind === 'refund' ? '10.00' : '13.81',
      }] }
    } else throw new Error(`Unexpected request: ${url.pathname}`)
    return { ok: true, json: async () => data } as Response
  }) as typeof fetch
})
afterEach(() => { cleanup(); global.fetch = originalFetch })

function metric(name: string) { return screen.getByRole('button', { name: new RegExp(`^${name} \\$`) }) }
function latestDetailRequest() { return requests.filter(url => url.pathname.endsWith('/transactions')).at(-1)! }

test('Card Benefits switches the single shared table, reconciles, and opens typed details; existing modes still work', async () => {
  render(createElement(HomePage))
  await screen.findByRole('heading', { name: 'Gross Spending by Category' })
  const spendingBadgeClass = screen.getByText('General Merchandise').parentElement!.className
  expect(metric('Gross Spending').getAttribute('aria-pressed')).toBe('true')
  expect(screen.queryByRole('heading', { name: 'Card Benefits by Category' })).toBeNull()
  fireEvent.click(metric('Card Benefits'))
  await waitFor(() => expect(requests.some(url => url.pathname.endsWith('/breakdown') && url.searchParams.get('mode') === 'benefits')).toBe(true))
  expect(metric('Card Benefits').hasAttribute('disabled')).toBe(false)
  expect(metric('Card Benefits').getAttribute('aria-pressed')).toBe('true')
  expect(metric('Card Benefits').parentElement!.className).toContain('ring-2')
  expect(metric('Gross Spending').getAttribute('aria-pressed')).toBe('false')
  expect(screen.getAllByRole('table')).toHaveLength(1)
  expect(screen.getByRole('heading', { name: 'Card Benefits by Category' })).toBeTruthy()
  const table = screen.getByRole('table')
  expect(within(table).getAllByRole('columnheader').map(node => node.textContent))
    .toEqual(['Benefit Category', 'Credits', 'Transactions'])
  const rows = within(table).getAllByRole('row').slice(1)
  expect(rows.map(row => within(row).getByRole('button').textContent)).toEqual(['Shopping', 'Transportation'])
  const shoppingBadge = within(table).getByRole('button', { name: 'Shopping' })
  expect(shoppingBadge.className).toContain(spendingBadgeClass.trim())
  expect(shoppingBadge.querySelector('svg')).not.toBeNull()
  const cents = rows.reduce((sum, row) => sum + Math.round(Number(within(row).getAllByRole('cell')[1].textContent!.replace('$', '')) * 100), 0)
  expect(cents).toBe(Math.round(Number(summary.card_benefits) * 100))
  fireEvent.click(shoppingBadge)
  await screen.findByText('Synthetic card_benefit')
  expect(latestDetailRequest().searchParams.get('benefit_category')).toBe('SHOPPING_CREDIT')
  expect(latestDetailRequest().searchParams.get('transaction_type')).toBe('card_benefit')
  expect(latestDetailRequest().searchParams.has('category')).toBe(false)
  fireEvent.click(metric('Refunds'))
  await waitFor(() => expect(requests.some(url => url.pathname.endsWith('/breakdown') && url.searchParams.get('mode') === 'spending')).toBe(true))
  expect(screen.queryByRole('heading', { name: 'Transaction Details' })).toBeNull()
  expect(screen.getByRole('heading', { name: 'Refunds by Category' })).toBeTruthy()
  fireEvent.click(within(screen.getByRole('table')).getAllByRole('row')[1])
  await screen.findByText('Synthetic refund')
  expect(latestDetailRequest().searchParams.get('transaction_type')).toBe('refund')
  expect(latestDetailRequest().searchParams.has('benefit_category')).toBe(false)
  fireEvent.click(metric('Gross Spending'))
  fireEvent.click(within(screen.getByRole('table')).getAllByRole('row')[1])
  await screen.findByText('Synthetic expense')
  expect(latestDetailRequest().searchParams.get('transaction_type')).toBe('expense')
  expect(latestDetailRequest().searchParams.get('category')).toBe('GENERAL_MERCHANDISE')
})

test('closing details and changing month retain the benefit mode and allow fresh drill-down', async () => {
  render(createElement(HomePage))
  await screen.findByRole('heading', { name: 'Gross Spending by Category' })
  fireEvent.click(metric('Card Benefits'))
  fireEvent.click(screen.getByRole('button', { name: 'Shopping' }))
  await screen.findByText('Synthetic card_benefit')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(screen.getByRole('heading', { name: 'Card Benefits by Category' })).toBeTruthy()
  expect(screen.queryByRole('heading', { name: 'Transaction Details' })).toBeNull()
  fireEvent.change(screen.getByLabelText('Month'), { target: { value: '2026-06' } })
  await waitFor(() => expect(requests.some(url => url.pathname.endsWith('/monthly') && url.searchParams.get('month') === '2026-06')).toBe(true))
  await screen.findByRole('heading', { name: 'Card Benefits by Category' })
  fireEvent.click(screen.getByRole('button', { name: 'Shopping' }))
  await screen.findByText('Synthetic card_benefit')
  expect(latestDetailRequest().searchParams.get('month')).toBe('2026-06')
})
