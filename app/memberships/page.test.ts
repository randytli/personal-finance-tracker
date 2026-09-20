/** @jest-environment jsdom */
import { createElement } from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import MembershipsPage from './page'

jest.mock('recharts', () => {
  const { createElement } = require('react')
  return {
    ResponsiveContainer: ({ children }: { children: unknown }) => children,
    LineChart: ({ data, children }: { data: unknown; children: unknown }) => createElement('div',
      { 'data-testid': 'trend', 'data-chart': JSON.stringify(data) }, children),
    CartesianGrid: () => null, Legend: () => null,
    Line: ({ dataKey, name }: { dataKey: string; name: string }) => createElement('span',
      { 'data-testid': 'trend-line', 'data-key': dataKey }, name),
    Tooltip: () => null, XAxis: () => null, YAxis: () => null,
  }
})
jest.mock('@/components/category-editor', () => ({ __esModule: true, default: () => null }))
jest.mock('@/components/label-editor', () => ({
  __esModule: true, default: () => null,
  useLabelOptions: () => ({ options: [], loading: false, error: null }),
}))

const metrics = {
  gross_charges: '100.00', refunds: '10.00', reimbursements: '51.00',
  unallocated_reimbursements: '51.00', card_benefits: '5.00', net_cost: '34.00',
  membership_transaction_count: 54, excluded_transaction_count: 0, unclassified_count: 0,
  reimbursement_transaction_count: 51, unallocated_reimbursement_transaction_count: 51,
}
const accounts = [
  { ...metrics, account_id: 'card', account_name: 'Platinum Card', account_mask: '1004',
    account_type: 'credit', account_subtype: 'credit card', institution_name: 'American Express',
    institution_id: 'ins_10', net_cost: '85.00', reimbursements: '0.00', unallocated_reimbursements: '0.00',
    reimbursement_transaction_count: 0, unallocated_reimbursement_transaction_count: 0, membership_transaction_count: 3 },
  { ...metrics, account_id: 'checking', account_name: 'Premier Plus Checking', account_mask: '1106',
    account_type: 'depository', account_subtype: 'checking', institution_name: 'Chase', institution_id: 'ins_56',
    gross_charges: '0.00', refunds: '0.00', card_benefits: '0.00', net_cost: '0.00', membership_transaction_count: 51 },
]
const transactions = [
  ...Array.from({ length: 51 }, (_, i) => ({ transaction_id: `reimbursement-${i}`, merchant_name: `Repayment ${i}`,
    amount: '1.00', transaction_type: 'reimbursement', account: accounts[1] })),
  { transaction_id: 'charge', merchant_name: 'Subscription charge', amount: '-100.00', transaction_type: 'expense', account: accounts[0] },
  { transaction_id: 'refund', merchant_name: 'Subscription refund', amount: '10.00', transaction_type: 'refund', account: accounts[0] },
  { transaction_id: 'benefit', merchant_name: 'Membership benefit', amount: '5.00', transaction_type: 'card_benefit', account: accounts[0] },
].map(value => ({ ...value, ...value.account, transaction_date: '2026-09-01', description: value.merchant_name,
  is_spending: value.transaction_type === 'expense', is_internal_transfer: false }))
const requests: URL[] = []
const originalFetch = global.fetch

beforeEach(() => {
  requests.length = 0
  global.fetch = jest.fn(async input => {
    const url = new URL(String(input), 'http://synthetic.test')
    requests.push(url)
    let data: unknown
    if (url.pathname.endsWith('/categories')) data = { categories: [] }
    else if (url.pathname.endsWith('/memberships')) {
      const end = url.searchParams.get('end_month')!
      const period = url.searchParams.get('period')
      data = { overall: metrics, accounts, period, end_month: end,
        start_month: period === 'ytd' ? end.slice(0, 4) + '-01' : '2025-10',
        type_counts: { charges: 1, refunds: 1, reimbursements: 51, card_benefits: 1, excluded: 0 },
        months: [{ month: end, ...metrics }] }
    } else if (url.pathname.endsWith('/transactions')) {
      const account = url.searchParams.get('account_id')
      const scoped = transactions.filter(value => !account || value.account_id === account)
      const kinds = { charges: 'expense', refunds: 'refund', reimbursements: 'reimbursement', card_benefits: 'card_benefit' }
      const view = url.searchParams.get('membership_view') as keyof typeof kinds | 'all'
      const filtered = scoped.filter(value => view === 'all' || value.transaction_type === kinds[view])
      const count = filtered.filter(value => value.transaction_type === 'reimbursement').length
      const offset = Number(url.searchParams.get('offset'))
      data = { total: filtered.length, transactions: filtered.slice(offset, offset + 50),
        unallocated_reimbursements: count.toFixed(2), unallocated_reimbursement_transaction_count: count,
        membership_counts: { all: scoped.length, ...Object.fromEntries(Object.entries(kinds).map(([key, kind]) =>
          [key, scoped.filter(value => value.transaction_type === kind).length])) } }
    } else throw new Error(`Unexpected request ${url.pathname}`)
    return { ok: true, json: async () => data } as Response
  }) as typeof fetch
})
afterEach(() => { cleanup(); global.fetch = originalFetch })
const latestDetails = () => requests.filter(url => url.pathname.endsWith('/transactions')).at(-1)!

test('shows backend overall/account costs, unallocated reconciliation, and reimbursement trend', async () => {
  render(createElement(MembershipsPage))
  const summary = await screen.findByRole('region', { name: 'Overall membership costs' })
  expect(within(summary).getByText('$34.00')).toBeTruthy()
  expect(within(summary).getByRole('button', { name: /Reimbursements \$51.00/ })).toBeTruthy()
  const reconciliation = screen.getByRole('region', { name: 'Membership reconciliation' })
  expect(within(reconciliation).getByText(/Unallocated reimbursements: \$51.00 · 51 transactions/)).toBeTruthy()
  expect(within(reconciliation).getByText('Sum of per-account net costs − unallocated reimbursements = overall net cost.')).toBeTruthy()
  expect(screen.getByText('$85.00 net cost')).toBeTruthy()
  expect(screen.getByText('$0.00 net cost')).toBeTruthy()
  expect(85 + 0 - Number(metrics.unallocated_reimbursements)).toBe(Number(metrics.net_cost))
  expect(JSON.parse(screen.getByTestId('trend').getAttribute('data-chart')!)[0]).toMatchObject({
    grossCharges: 100, refunds: 10, reimbursements: 51, cardBenefits: 5, netCost: 34,
  })
  expect(screen.getAllByTestId('trend-line').map(line => line.textContent)).toEqual([
    'Gross charges', 'Refunds', 'Reimbursements', 'Card benefits', 'Net cost',
  ])
})

test('each summary card opens its matching existing transaction view', async () => {
  render(createElement(MembershipsPage))
  const summary = await screen.findByRole('region', { name: 'Overall membership costs' })
  for (const [name, view] of [
    ['Gross charges', 'charges'], ['Refunds', 'refunds'], ['Reimbursements', 'reimbursements'],
    ['Card benefits', 'card_benefits'], ['Net cost', 'all'],
  ] as const) {
    fireEvent.click(within(summary).getByRole('button', { name: new RegExp(`^${name}`) }))
    await waitFor(() => expect(latestDetails().searchParams.get('membership_view')).toBe(view))
    expect(latestDetails().searchParams.has('account_id')).toBe(false)
  }
  expect(within(summary).getByRole('button', { name: /Net cost.*View all transactions/ })).toBeTruthy()
})

test('reimbursement drill-down retains full-filter totals across pages, source-account filters, and periods', async () => {
  render(createElement(MembershipsPage))
  const summary = await screen.findByRole('region', { name: 'Overall membership costs' })
  fireEvent.click(within(summary).getByRole('button', { name: /Reimbursements/ }))
  await screen.findByText(/Unallocated reimbursements in this filter: \$51.00 · 51 transactions across all pages/)
  fireEvent.click(within(summary).getByRole('button', { name: /Reimbursements/ }))
  expect(screen.getAllByText(/Reduces overall cost only/)).toHaveLength(50)
  expect(latestDetails().searchParams.get('membership_view')).toBe('reimbursements')
  expect(screen.getAllByText(/Reduces overall cost only/)).toHaveLength(50)
  expect(screen.getAllByText('CHASE CHECKING · 1106').length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await screen.findByText('Repayment 50')
  expect(latestDetails().searchParams.get('offset')).toBe('50')
  expect(screen.getByText(/Unallocated reimbursements in this filter: \$51.00 · 51 transactions across all pages/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'View reimbursements received' }))
  await waitFor(() => expect(latestDetails().searchParams.get('account_id')).toBe('checking'))
  expect(latestDetails().searchParams.get('offset')).toBe('0')
  fireEvent.change(screen.getByLabelText('Period'), { target: { value: 'ytd' } })
  await waitFor(() => expect(latestDetails().searchParams.get('start_month')).toMatch(/-01$/))
  expect(latestDetails().searchParams.has('account_id')).toBe(false)
  expect(latestDetails().searchParams.get('membership_view')).toBe('reimbursements')
  await screen.findByRole('button', { name: 'Refunds (1)' })
  fireEvent.click(screen.getByRole('button', { name: 'Refunds (1)' }))
  await screen.findByText('Subscription refund', { selector: 'p.font-medium' })
  fireEvent.click(screen.getByRole('button', { name: 'View $5.00 benefits' }))
  await screen.findByText('Membership benefit', { selector: 'p.font-medium' })
  expect(latestDetails().searchParams.get('membership_view')).toBe('card_benefits')
  expect(latestDetails().searchParams.get('account_id')).toBe('card')
})
