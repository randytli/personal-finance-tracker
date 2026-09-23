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
  reimbursements: '20.00', net_spending: '46.20', income: '0.00', net_savings: '-46.20', unclassified_count: 0,
  category_breakdown: [{ category: 'GENERAL_MERCHANDISE', gross_spending: '100.00',
    refunds: '10.00', reimbursements: '15.00', expense_transaction_count: 1,
    refund_transaction_count: 1, reimbursement_transaction_count: 1 },
    { category: 'UNCATEGORIZED', gross_spending: '0.00', refunds: '0.00',
      reimbursements: '5.00', expense_transaction_count: 0,
      refund_transaction_count: 0, reimbursement_transaction_count: 2 }],
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
    if (url.pathname.endsWith('/sync/status')) data = { last_published_run_id: null, published_at: null,
      current_run: null, jobs: { status: 'stopped', heartbeat_at: null },
      backup: { status: 'never', last_success_at: null, last_attempt_at: null, error_category: null }, institutions: [] }
    else if (url.pathname.endsWith('/monthly')) data = { ...summary, month: url.searchParams.get('month') }
    else if (url.pathname.endsWith('/trend')) data = { months: [] }
    else if (url.pathname.endsWith('/breakdown')) {
      data = { groups: url.searchParams.get('mode') === 'reimbursements'
        ? url.searchParams.get('group_by') === 'account'
          ? [{ institution_id: 'ins_56', institution_name: 'Chase', account_id: 'checking', account_name: 'Checking',
              account_mask: '1106', account_type: 'depository', reimbursements: '15.00', reimbursement_transaction_count: 1 },
             { institution_id: 'ins_10', institution_name: 'American Express', account_id: 'gold', account_name: 'Gold',
              account_mask: '3008', account_type: 'credit', reimbursements: '5.00', reimbursement_transaction_count: 2 }]
          : [{ institution_id: 'ins_56', institution_name: 'Chase', reimbursements: '15.00', reimbursement_transaction_count: 1 },
             { institution_id: 'ins_10', institution_name: 'American Express', reimbursements: '5.00', reimbursement_transaction_count: 2 }]
        : [] }
    }
    else if (url.pathname.endsWith('/benefit-categories')) data = { categories: [
      { value: 'SHOPPING_CREDIT', label: 'Shopping' },
      { value: 'TRANSPORTATION_CREDIT', label: 'Transportation' },
    ] }
    else if (url.pathname.endsWith('/categories')) data = { categories: [] }
    else if (url.pathname.endsWith('/transactions')) {
      const kind = url.searchParams.get('transaction_type')
      const category = url.searchParams.get('category')
      if (kind === 'reimbursement') {
        const all = [
          { transaction_id: 'repayment-1', merchant_name: 'Repayment one', amount: '15.00', category: 'GENERAL_MERCHANDISE', institution: 'ins_56', account: 'checking' },
          { transaction_id: 'repayment-2', merchant_name: 'Repayment two', amount: '3.00', category: 'UNCATEGORIZED', institution: 'ins_10', account: 'gold' },
          { transaction_id: 'repayment-3', merchant_name: 'Repayment three', amount: '2.00', category: 'UNCATEGORIZED', institution: 'ins_10', account: 'gold' },
        ].filter(value => (!category || value.category === category)
          && (!url.searchParams.has('institution_id') || value.institution === url.searchParams.get('institution_id'))
          && (!url.searchParams.has('account_id') || value.account === url.searchParams.get('account_id')))
        data = { total: all.length, reimbursements: all.reduce((total, value) => total + Number(value.amount), 0).toFixed(2),
          transactions: all.map(value => ({ ...value, transaction_date: `${url.searchParams.get('month')}-12`,
            description: 'Synthetic repayment', transaction_type: kind, effective_category: value.category })) }
      } else data = { total: 1, transactions: [{ transaction_id: 'synthetic',
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

test('Reimbursements reconcile across categories and institution/account filters without stale mode filters', async () => {
  render(createElement(HomePage))
  await screen.findByRole('heading', { name: 'Gross Spending by Category' })
  fireEvent.click(metric('Reimbursements'))
  expect(metric('Reimbursements').getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('heading', { name: 'Reimbursements by Category' })).toBeTruthy()
  const table = screen.getByRole('table')
  expect(within(table).getAllByRole('columnheader').map(node => node.textContent))
    .toEqual(['Category', 'Reimbursements', 'Transactions'])
  const rows = within(table).getAllByRole('row').slice(1)
  expect(rows.map(row => within(row).getAllByRole('cell')[2].textContent)).toEqual(['1', '2'])
  expect(rows.reduce((total, row) => total + Number(within(row).getAllByRole('cell')[1].textContent!.replace('$', '')), 0))
    .toBe(Number(summary.reimbursements))

  const institutionSection = screen.getByRole('heading', { name: 'Reimbursements by institution' }).closest('section')!
  await waitFor(() => expect(within(institutionSection).getAllByRole('button')).toHaveLength(2))
  const institutionAmounts = within(institutionSection).getAllByRole('button').map(button =>
    Number(button.textContent!.match(/\$(\d+\.\d{2})/)![1]))
  expect(institutionAmounts).toEqual([15, 5])
  expect(institutionAmounts.reduce((total, amount) => total + amount, 0)).toBe(Number(summary.reimbursements))

  fireEvent.click(within(table).getByRole('row', { name: /Uncategorized/i }))
  await screen.findByText('Repayment two')
  expect(screen.getByText('2 matching transactions')).toBeTruthy()
  expect(screen.getByText('Total reimbursements: $5.00')).toBeTruthy()
  expect(latestDetailRequest().searchParams.get('transaction_type')).toBe('reimbursement')
  expect(latestDetailRequest().searchParams.get('category')).toBe('UNCATEGORIZED')
  fireEvent.click(within(institutionSection).getByRole('button', { name: /AMERICAN EXPRESS/i }))
  await waitFor(() => expect(latestDetailRequest().searchParams.get('institution_id')).toBe('ins_10'))
  expect(screen.getByText('Total reimbursements: $5.00')).toBeTruthy()

  fireEvent.change(within(institutionSection).getByRole('combobox'), { target: { value: 'account' } })
  const accountSection = screen.getByRole('heading', { name: 'Reimbursements by account' }).closest('section')!
  await waitFor(() => expect(within(accountSection).getAllByRole('button')).toHaveLength(2))
  expect(within(accountSection).getAllByRole('button').map(button =>
    Number(button.textContent!.match(/\$(\d+\.\d{2})/)![1])).reduce((total, amount) => total + amount, 0))
    .toBe(Number(summary.reimbursements))
  fireEvent.click(within(accountSection).getByRole('button', { name: /3008/i }))
  await waitFor(() => expect(latestDetailRequest().searchParams.get('account_id')).toBe('gold'))
  expect(screen.getByText('Total reimbursements: $5.00')).toBeTruthy()
  fireEvent.click(within(accountSection).getByRole('button', { name: /3008/i }))
  await waitFor(() => expect(latestDetailRequest().searchParams.has('account_id')).toBe(false))

  fireEvent.click(metric('Card Benefits'))
  expect(screen.queryByRole('heading', { name: 'Transaction Details' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Shopping' }))
  await screen.findByText('Synthetic card_benefit')
  expect(latestDetailRequest().searchParams.has('category')).toBe(false)
  fireEvent.click(metric('Reimbursements'))
  fireEvent.click(within(screen.getByRole('table')).getByRole('row', { name: /General Merchandise/i }))
  await screen.findByText('Repayment one')
  expect(screen.getByText('Total reimbursements: $15.00')).toBeTruthy()
  expect(latestDetailRequest().searchParams.has('benefit_category')).toBe(false)
  fireEvent.change(screen.getByLabelText('Month'), { target: { value: '2026-06' } })
  await waitFor(() => expect(requests.some(url => url.pathname.endsWith('/monthly') && url.searchParams.get('month') === '2026-06')).toBe(true))
  expect(screen.queryByRole('heading', { name: 'Transaction Details' })).toBeNull()
  await screen.findByRole('heading', { name: 'Reimbursements by Category' })
})

test('reimbursement detail pagination keeps the full filtered amount', async () => {
  const baseFetch = global.fetch
  global.fetch = jest.fn(async (input) => {
    const url = new URL(String(input), 'http://synthetic.test')
    if (url.pathname.endsWith('/transactions') && url.searchParams.get('transaction_type') === 'reimbursement') {
      requests.push(url)
      const offset = Number(url.searchParams.get('offset') || 0)
      const count = offset === 0 ? 100 : 1
      return { ok: true, json: async () => ({ total: 101, reimbursements: '101.00',
        transactions: Array.from({ length: count }, (_, index) => ({
          transaction_id: `reimbursement-${offset + index}`, transaction_date: '2026-08-12',
          merchant_name: `Repayment ${offset + index}`, description: 'Synthetic repayment',
          transaction_type: 'reimbursement', amount: '1.00',
        })) }) } as Response
    }
    return baseFetch(input)
  }) as typeof fetch
  render(createElement(HomePage))
  await screen.findByRole('heading', { name: 'Gross Spending by Category' })
  fireEvent.click(metric('Reimbursements'))
  fireEvent.click(within(screen.getByRole('table')).getByRole('row', { name: /Uncategorized/i }))
  await screen.findByText('101 matching transactions')
  expect(screen.getByText('Total reimbursements: $101.00')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() => expect(latestDetailRequest().searchParams.get('offset')).toBe('100'))
  await screen.findByText('Repayment 100')
  expect(screen.getByText('Total reimbursements: $101.00')).toBeTruthy()
  expect(screen.getByText('101–101 of 101')).toBeTruthy()
})
