/** @jest-environment jsdom */
import { createElement } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import HomePage from './page'

jest.mock('recharts', () => ({ ResponsiveContainer: () => null, CartesianGrid: () => null,
  Line: () => null, LineChart: () => null, Tooltip: () => null, XAxis: () => null, YAxis: () => null }))
jest.mock('@/components/plaid-link-button', () => () => null)
jest.mock('@/components/category-editor', () => ({ __esModule: true, default: () => null }))
jest.mock('@/components/benefit-category-editor', () => ({ __esModule: true, default: () => null }))
jest.mock('@/components/label-editor', () => ({ __esModule: true, default: () => null,
  useLabelOptions: () => ({ options: [{ value: 'tech-id', label: 'tech', is_system: false },
    { value: 'old-id', label: 'old gear', is_system: false, archived: true }], loading: false, error: null }) }))

const categories = [
  { category: 'DINING', gross_spending: '100.00', refunds: '10.00', reimbursements: '15.00', card_benefits: '20.00', net_spending: '55.00',
    expense_transaction_count: 1, refund_transaction_count: 1, reimbursement_transaction_count: 1, benefit_transaction_count: 1, contributing_transaction_count: 4 },
  { category: 'GROCERIES', gross_spending: '60.00', refunds: '0.00', reimbursements: '0.00', card_benefits: '0.00', net_spending: '60.00',
    expense_transaction_count: 1, refund_transaction_count: 0, reimbursement_transaction_count: 0, benefit_transaction_count: 0, contributing_transaction_count: 1 },
  { category: 'ENTERTAINMENT', gross_spending: '0.00', refunds: '0.00', reimbursements: '0.00', card_benefits: '25.00', net_spending: '-25.00',
    expense_transaction_count: 0, refund_transaction_count: 0, reimbursement_transaction_count: 0, benefit_transaction_count: 1, contributing_transaction_count: 1 },
  { category: 'UNCATEGORIZED', gross_spending: '0.00', refunds: '0.00', reimbursements: '5.00', card_benefits: '0.00', net_spending: '-5.00',
    expense_transaction_count: 0, refund_transaction_count: 0, reimbursement_transaction_count: 2, benefit_transaction_count: 0, contributing_transaction_count: 2 },
]
const summary = { gross_spending: '160.00', refunds: '10.00', reimbursements: '20.00', card_benefits: '45.00',
  net_spending: '85.00', income: '0.00', net_savings: '-85.00', unclassified_count: 0,
  category_breakdown: [], benefit_category_breakdown: [], category_attribution_version: 1, category_net_breakdown: categories }
const requests: URL[] = []
const originalFetch = global.fetch
const originalMedia = window.matchMedia
const originalScroll = Element.prototype.scrollIntoView
let width = 1440

beforeEach(() => {
  width = 1440
  requests.length = 0
  window.matchMedia = jest.fn().mockImplementation(query => ({ matches: query.includes('max-width') ? width < 768 : width >= 768, media: query,
    addEventListener: jest.fn(), removeEventListener: jest.fn() }))
  Element.prototype.scrollIntoView = jest.fn()
  global.fetch = jest.fn(async input => {
    const url = new URL(String(input), 'http://synthetic.test')
    requests.push(url)
    let data: unknown
    if (url.pathname.endsWith('/sync/status')) data = { last_published_run_id: null, published_at: null, current_run: null,
      jobs: { status: 'running', heartbeat_at: null }, backup: { status: 'healthy' }, institutions: [] }
    else if (url.pathname.endsWith('/monthly')) data = { ...summary, month: url.searchParams.get('month') }
    else if (url.pathname.endsWith('/trend')) data = { months: [] }
    else if (url.pathname.endsWith('/breakdown')) data = { groups: [
      { institution_id: 'ins_56', institution_name: 'Chase', account_id: url.searchParams.get('group_by') === 'account' ? 'checking' : undefined,
        account_name: 'Checking', account_mask: '1106', account_type: 'depository', reimbursements: '15.00', reimbursement_transaction_count: 1,
        gross_spending: '160.00', refunds: '10.00', card_benefits: '20.00', net_spending: '115.00' },
      { institution_id: 'ins_10', institution_name: 'American Express', account_id: url.searchParams.get('group_by') === 'account' ? 'gold' : undefined,
        account_name: 'Gold', account_mask: '3008', account_type: 'credit', reimbursements: '5.00', reimbursement_transaction_count: 2,
        gross_spending: '0.00', refunds: '0.00', card_benefits: '25.00', net_spending: '-30.00' },
    ] }
    else if (url.pathname.endsWith('/categories') || url.pathname.endsWith('/benefit-categories')) data = { categories: [] }
    else if (url.pathname.endsWith('/transactions')) {
      const code = url.searchParams.get('canonical_category')
      const component = url.searchParams.get('spending_component')
      const category = categories.find(value => value.category === code)
      if (category && component) {
        const parts = [ ['gross', 'gross_spending', 'expense_transaction_count', 'expense'],
          ['refunds', 'refunds', 'refund_transaction_count', 'refund'],
          ['reimbursements', 'reimbursements', 'reimbursement_transaction_count', 'reimbursement'],
          ['card_benefits', 'card_benefits', 'benefit_transaction_count', 'card_benefit'] ] as const
        const transactions = parts.filter(part => component === 'net' || part[0] === component).flatMap(part =>
          Array.from({ length: category[part[2]] }, (_, index) => {
            const magnitude = Number(category[part[1]]) / category[part[2]]
            return { transaction_id: `${code}-${part[0]}-${index}`, transaction_date: `${url.searchParams.get('month')}-12`,
              merchant_name: `${code} ${part[0]} ${index}`, description: 'Synthetic contribution', transaction_type: part[3],
              amount: (part[0] === 'gross' ? -magnitude : magnitude).toFixed(2),
              net_contribution: (part[0] === 'gross' ? magnitude : -magnitude).toFixed(2) }
          }))
        data = { total: transactions.length, component_totals: category, transactions }
      } else data = { total: 1, transactions: [{ transaction_id: 'legacy', transaction_date: '2026-09-12',
        merchant_name: 'Legacy detail', transaction_type: url.searchParams.get('transaction_type'), amount: '1.00' }] }
    } else throw new Error(`Unexpected ${url.pathname}`)
    return { ok: true, json: async () => data } as Response
  }) as typeof fetch
})
afterEach(async () => {
  await act(async () => { await Promise.resolve() })
  cleanup(); global.fetch = originalFetch; window.matchMedia = originalMedia; Element.prototype.scrollIntoView = originalScroll
})

async function click(element: Element) { await act(async () => { fireEvent.click(element) }) }
async function change(element: Element, event: Parameters<typeof fireEvent.change>[1]) { await act(async () => { fireEvent.change(element, event) }) }

function metric(name: string) { return screen.getByRole('button', { name: new RegExp(`^${name} \\$`) }) }
function table(title = 'Net Spending') { return screen.getByRole('table', { name: `${title} by Category` }) }
function detailRequests() { return requests.filter(url => url.pathname.endsWith('/transactions')) }
function latestDetails() { return detailRequests().at(-1)! }
function row(name: string, title = 'Net Spending') { return Array.from(table(title).querySelectorAll('tr[data-category]')).find(node => node.textContent!.includes(name))! as HTMLElement }
function chevron(name: string, scope: HTMLElement = row(name)) { return within(scope).getByRole('button', { name: `Breakdown for ${name}` }) }
async function ready() { render(createElement(HomePage)); await screen.findByRole('table', { name: 'Net Spending by Category' }) }

test('Net Spending controls the only compact category view by default; income does not change it', async () => {
  await ready()
  expect(metric('Net Spending').getAttribute('aria-pressed')).toBe('true')
  expect(metric('Gross Spending').getAttribute('aria-pressed')).toBe('false')
  expect(screen.getAllByRole('table')).toHaveLength(1)
  expect(within(table()).getAllByRole('columnheader').map(node => node.textContent)).toEqual(['Category', 'Net Spending', 'Transactions'])
  expect(screen.queryByRole('heading', { name: 'Gross Spending by Category' })).toBeNull()
  await click(metric('Income'))
  await screen.findByText('Legacy detail')
  expect(metric('Net Spending').getAttribute('aria-pressed')).toBe('true')
  expect(latestDetails().searchParams.get('transaction_type')).toBe('income')
  expect(screen.getByRole('link', { name: 'Review' }).getAttribute('href')).toBe('/review')
  expect(screen.getByRole('link', { name: 'Memberships' }).getAttribute('href')).toBe('/memberships')
})

test('all five cards switch titles, amounts, counts and canonical component drill-down', async () => {
  await ready()
  for (const [name, component, amount, count] of [
    ['Gross Spending', 'gross', '$100.00', '1'], ['Refunds', 'refunds', '$10.00', '1'],
    ['Reimbursements', 'reimbursements', '$15.00', '1'], ['Card Benefits', 'card_benefits', '$20.00', '1'],
    ['Net Spending', 'net', '$55.00', '4'],
  ]) {
    await click(metric(name))
    expect(metric(name).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('heading', { name: `${name} by Category` })).toBeTruthy()
    const cells = within(row('Dining', name)).getAllByRole('cell')
    expect(cells[1].textContent).toBe(amount)
    expect(cells[2].textContent).toBe(count)
    await click(within(row('Dining', name)).getByRole('button', { name: /transactions for/ }))
    await waitFor(() => expect(latestDetails().searchParams.get('spending_component')).toBe(component))
    expect(latestDetails().searchParams.get('canonical_category')).toBe('DINING')
    expect(latestDetails().searchParams.has('category')).toBe(false)
    expect(latestDetails().searchParams.has('benefit_category')).toBe(false)
  }
})

test('signed descending sorting preserves negative and credit-only categories', async () => {
  await ready()
  expect(within(table()).getAllByRole('row').slice(1).map(node => within(node).getAllByRole('cell')[0].textContent))
    .toEqual(['Groceries', 'Dining', 'Uncategorized', 'Entertainment'])
  expect(within(row('Entertainment')).getAllByRole('cell')[1].textContent).toBe('-$25.00')
  await click(metric('Card Benefits'))
  expect(within(table('Card Benefits')).getAllByRole('row').slice(1).map(node => within(node).getAllByRole('cell')[0].textContent))
    .toEqual(['Entertainment', 'Dining'])
})

test('zero net with contributing transactions remains visible', async () => {
  const base = global.fetch
  global.fetch = jest.fn(async input => {
    const url = new URL(String(input), 'http://synthetic.test')
    if (url.pathname.endsWith('/monthly')) return { ok: true, json: async () => ({ ...summary,
      category_net_breakdown: [{ ...categories[0], net_spending: '0.00' }] }) } as Response
    return base(input)
  }) as typeof fetch
  await ready()
  expect(within(row('Dining')).getAllByRole('cell')[1].textContent).toBe('$0.00')
})

test.each([768, 1440])('inline category disclosures at %ipx expand, collapse and switch from the chevron without a sheet', async viewport => {
  width = viewport
  await ready()
  expect(screen.queryByRole('button', { name: 'View full breakdown' })).toBeNull()
  expect(screen.queryByRole('dialog')).toBeNull()
  await click(chevron('Dining'))
  const breakdown = screen.getByRole('group', { name: 'Breakdown for Dining' })
  const amounts = ['$100.00', '$10.00', '$15.00', '$20.00', '$55.00']
  const counts = [1, 1, 1, 1, 4]
  within(breakdown).getAllByRole('button').forEach((button, index) => {
    expect(button.textContent).toContain(amounts[index])
    expect(button.textContent).toContain(`${counts[index]} transaction`)
  })
  expect(chevron('Dining').getAttribute('aria-expanded')).toBe('true')
  expect(chevron('Dining').getAttribute('aria-controls')).toBe(breakdown.id)
  await click(chevron('Entertainment'))
  expect(screen.queryByRole('group', { name: 'Breakdown for Dining' })).toBeNull()
  const negative = screen.getByRole('group', { name: 'Breakdown for Entertainment' })
  expect(within(negative).getByRole('button', { name: /Gross Spending transactions/ }).textContent).toContain('$0.00')
  expect(within(negative).getByRole('button', { name: /Gross Spending transactions/ }).textContent).toContain('0 transactions')
  expect(within(negative).getByRole('button', { name: /Net Spending transactions/ }).textContent).toContain('-$25.00')
  await click(chevron('Entertainment'))
  expect(screen.queryByRole('group', { name: 'Breakdown for Entertainment' })).toBeNull()
  expect(chevron('Entertainment').getAttribute('aria-expanded')).toBe('false')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(detailRequests()).toHaveLength(0)
  await click(metric('Gross Spending'))
  await click(chevron('Dining', row('Dining', 'Gross Spending')))
  expect(within(screen.getByRole('group', { name: 'Breakdown for Dining' })).getByRole('button', { name: /Net Spending transactions/ }).textContent).toContain('$55.00')
})

test('crossing to desktop closes the mobile sheet and removes its entry point', async () => {
  width = 390
  render(createElement(HomePage))
  await screen.findByRole('heading', { name: 'Net Spending by Category' })
  await click(screen.getByRole('button', { name: 'View full breakdown' }))
  expect(screen.getByRole('dialog')).toBeTruthy()
  const mockMedia = window.matchMedia as jest.Mock
  const index = mockMedia.mock.calls.findIndex(([query]) => query === '(min-width: 768px)')
  const media = mockMedia.mock.results[index].value
  media.matches = true
  await act(async () => { media.addEventListener.mock.calls[0][1]() })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.queryByRole('button', { name: 'View full breakdown' })).toBeNull()
  expect(table()).toBeTruthy()
})

test('keyboard category activation uses native buttons, presses the row and keeps signed detail totals', async () => {
  await ready()
  expect(row('Dining').hasAttribute('tabindex')).toBe(false)
  expect(row('Dining').hasAttribute('aria-selected')).toBe(false)
  chevron('Dining').focus()
  expect(document.activeElement).toBe(chevron('Dining'))
  await click(chevron('Dining'))
  const sub = within(screen.getByRole('group', { name: 'Breakdown for Dining' })).getByRole('button', { name: /Net Spending transactions/ })
  expect(sub.tagName).toBe('BUTTON')
  await click(sub)
  await screen.findByText('DINING gross 0')
  expect(sub.getAttribute('aria-pressed')).toBe('true')
  expect(within(row('Dining')).getByRole('button', { name: /^Net Spending transactions for Dining/ }).getAttribute('aria-pressed')).toBe('true')
  expect(within(screen.getByLabelText('Active detail filters')).getByText('Dining')).toBeTruthy()
  expect(screen.getByText('Net contribution: $55.00')).toBeTruthy()
  expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })
})

test('metric and month changes clear stale details but retain the selected metric', async () => {
  await ready()
  await click(metric('Card Benefits'))
  await click(within(row('Entertainment', 'Card Benefits')).getByRole('button', { name: /transactions for/ }))
  await screen.findByText('ENTERTAINMENT card_benefits 0')
  await click(screen.getByRole('button', { name: 'Close' }))
  expect(table('Card Benefits')).toBeTruthy()
  await change(screen.getByLabelText('Month'), { target: { value: '2026-06' } })
  await waitFor(() => expect(requests.some(url => url.pathname.endsWith('/monthly') && url.searchParams.get('month') === '2026-06')).toBe(true))
  await screen.findByRole('table', { name: 'Card Benefits by Category' })
  await click(within(row('Entertainment', 'Card Benefits')).getByRole('button', { name: /transactions for/ }))
  await screen.findByText('ENTERTAINMENT card_benefits 0')
  expect(latestDetails().searchParams.get('month')).toBe('2026-06')
  await click(metric('Refunds'))
  expect(screen.queryByRole('heading', { name: 'Transaction Details' })).toBeNull()
})

test('institution/account secondary filters preserve the canonical reimbursement component', async () => {
  await ready()
  await click(metric('Reimbursements'))
  await click(within(row('Uncategorized', 'Reimbursements')).getByRole('button', { name: /transactions for/ }))
  await screen.findByText('UNCATEGORIZED reimbursements 0')
  const section = screen.getByRole('heading', { name: 'Reimbursements by institution' }).closest('section')!
  await click(within(section).getByRole('button', { name: /AMERICAN EXPRESS/i }))
  await waitFor(() => expect(latestDetails().searchParams.get('institution_id')).toBe('ins_10'))
  expect(latestDetails().searchParams.get('canonical_category')).toBe('UNCATEGORIZED')
  expect(latestDetails().searchParams.get('spending_component')).toBe('reimbursements')
  await change(within(section).getByRole('combobox'), { target: { value: 'account' } })
  await waitFor(() => expect(within(section).getByRole('button', { name: /3008/i })).toBeTruthy())
  await click(within(section).getByRole('button', { name: /3008/i }))
  await waitFor(() => expect(latestDetails().searchParams.get('account_id')).toBe('gold'))
  expect(screen.getByText('Reimbursements: $5.00')).toBeTruthy()
})

test('complete canonical pagination retains full-filter reconciliation across pages', async () => {
  const base = global.fetch
  global.fetch = jest.fn(async input => {
    const url = new URL(String(input), 'http://synthetic.test')
    if (url.pathname.endsWith('/transactions') && url.searchParams.get('spending_component') === 'net') {
      requests.push(url)
      const offset = Number(url.searchParams.get('offset') || 0)
      return { ok: true, json: async () => ({ total: 101, component_totals: { net_spending: '55.00' },
        transactions: Array.from({ length: offset === 0 ? 100 : 1 }, (_, index) => ({ transaction_id: `page-${offset + index}`,
          transaction_date: '2026-09-12', merchant_name: `Contribution ${offset + index}`, transaction_type: 'expense',
          amount: offset === 0 ? '-0.50' : '-5.00', net_contribution: offset === 0 ? '0.50' : '5.00' })) }) } as Response
    } return base(input)
  }) as typeof fetch
  await ready()
  await click(within(row('Dining')).getByRole('button', { name: /transactions for/ }))
  await screen.findByText('101 matching transactions')
  expect(screen.getByText('Net contribution: $55.00')).toBeTruthy()
  await click(screen.getByRole('button', { name: 'Next' }))
  await screen.findByText('Contribution 100')
  expect(latestDetails().searchParams.get('offset')).toBe('100')
  expect(latestDetails().searchParams.get('canonical_category')).toBe('DINING')
  expect(latestDetails().searchParams.get('spending_component')).toBe('net')
  expect(screen.getByText('Net contribution: $55.00')).toBeTruthy()
  expect(screen.getByText('101–101 of 101')).toBeTruthy()
})

test('mobile compact list and disclosure sheet use chevron buttons with negative and zero components, never a table', async () => {
  width = 390
  render(createElement(HomePage))
  await screen.findByRole('heading', { name: 'Net Spending by Category' })
  expect(screen.queryByRole('table')).toBeNull()
  const list = screen.getByLabelText('Net Spending category list')
  const listRow = list.querySelector<HTMLElement>('[data-category="DINING"]')!
  const listMain = within(listRow).getByRole('button', { name: /Dining.*4 transactions/ })
  expect(listMain.textContent).toContain('$55.00')
  expect(listMain.getAttribute('aria-pressed')).toBe('false')
  await click(chevron('Dining', listRow))
  expect(within(listRow).getAllByRole('button', { name: /transactions for Dining/ })).toHaveLength(5)
  expect(detailRequests()).toHaveLength(0)
  await click(chevron('Dining', listRow))
  expect(within(listRow).queryByRole('group')).toBeNull()
  await click(screen.getByRole('button', { name: 'View full breakdown' }))
  const dialog = await screen.findByRole('dialog', { name: 'Full category breakdown' })
  expect(within(dialog).queryByRole('table')).toBeNull()
  expect(dialog.querySelector('details, summary')).toBeNull()
  const sheetRow = dialog.querySelector<HTMLElement>('[data-category="ENTERTAINMENT"]')!
  expect(chevron('Entertainment', sheetRow).getAttribute('aria-expanded')).toBe('false')
  expect(within(sheetRow).getByRole('button', { pressed: false }).textContent).toContain('-$25.00')
  await click(chevron('Entertainment', sheetRow))
  expect(chevron('Entertainment', sheetRow).getAttribute('aria-expanded')).toBe('true')
  const group = within(sheetRow).getByRole('group', { name: 'Breakdown for Entertainment' })
  expect(within(group).getAllByRole('button')).toHaveLength(5)
  expect(within(group).getByRole('button', { name: /Gross Spending transactions.*\$0.00/ })).toBeTruthy()
  expect(within(sheetRow).getAllByRole('button').some(button => button.querySelector('button'))).toBe(false)
  await click(chevron('Entertainment', sheetRow))
  expect(within(sheetRow).queryByRole('group')).toBeNull()
  expect(detailRequests()).toHaveLength(0)
  await click(within(dialog).getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await click(screen.getByRole('button', { name: 'View full breakdown' }))
  expect(await screen.findByRole('dialog')).toBeTruthy()
})

test.each([390, 768, 1440])('responsive breakdown drill-down at %ipx uses canonical API filters', async viewport => {
  width = viewport
  render(createElement(HomePage))
  await screen.findByRole('heading', { name: 'Net Spending by Category' })
  let content: HTMLElement
  if (viewport < 768) {
    await click(screen.getByRole('button', { name: 'View full breakdown' }))
    content = await screen.findByRole('dialog')
    await click(chevron('Dining', content.querySelector<HTMLElement>('[data-category="DINING"]')!))
  } else {
    await click(chevron('Dining'))
    content = screen.getByRole('group', { name: 'Breakdown for Dining' })
  }
  await click(within(content).getByRole('button', { name: /Card Benefits transactions for Dining/ }))
  await screen.findByText('DINING card_benefits 0')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(latestDetails().searchParams.get('canonical_category')).toBe('DINING')
  expect(latestDetails().searchParams.get('spending_component')).toBe('card_benefits')
})

test('a category row toggles its transactions, the chevron only toggles its breakdown, and sub-rows toggle', async () => {
  await ready()
  const main = () => within(row('Dining')).getByRole('button', { name: /^Net Spending transactions for Dining/ })
  expect(main().getAttribute('aria-pressed')).toBe('false')
  await click(row('Dining'))
  await screen.findByText('DINING gross 0')
  expect(detailRequests()).toHaveLength(1)
  expect(latestDetails().searchParams.get('canonical_category')).toBe('DINING')
  expect(latestDetails().searchParams.get('spending_component')).toBe('net')
  expect(main().getAttribute('aria-pressed')).toBe('true')
  expect(within(row('Dining')).getAllByRole('cell')[0].textContent).toBe('Dining')
  await click(row('Dining'))
  await waitFor(() => expect(screen.queryByText('DINING gross 0')).toBeNull())
  expect(main().getAttribute('aria-pressed')).toBe('false')
  await click(main())
  await screen.findByText('DINING gross 0')
  expect(main().getAttribute('aria-pressed')).toBe('true')
  await click(main())
  await waitFor(() => expect(screen.queryByText('DINING gross 0')).toBeNull())
  const before = detailRequests().length
  await click(chevron('Dining'))
  const group = screen.getByRole('group', { name: 'Breakdown for Dining' })
  expect(main().getAttribute('aria-pressed')).toBe('false')
  await click(chevron('Dining'))
  expect(screen.queryByRole('group', { name: 'Breakdown for Dining' })).toBeNull()
  expect(group.isConnected).toBe(false)
  expect(detailRequests()).toHaveLength(before)
  await click(chevron('Dining'))
  const refunds = () => within(screen.getByRole('group', { name: 'Breakdown for Dining' })).getByRole('button', { name: /^Refunds transactions for Dining/ })
  await click(refunds())
  await screen.findByText('DINING refunds 0')
  expect(latestDetails().searchParams.get('spending_component')).toBe('refunds')
  expect(refunds().getAttribute('aria-pressed')).toBe('true')
  expect(main().getAttribute('aria-pressed')).toBe('false')
  await click(refunds())
  await waitFor(() => expect(screen.queryByText('DINING refunds 0')).toBeNull())
  expect(refunds().getAttribute('aria-pressed')).toBe('false')
  expect(screen.getByRole('group', { name: 'Breakdown for Dining' })).toBeTruthy()
})

function donut(title = 'Net Spending') { return screen.getByRole('group', { name: `Share of ${title} by category` }).parentElement! as HTMLElement }
function segment(name: RegExp | string) { return within(donut()).getByRole('button', { name }) }

test('the donut shows the metric total and draws only positive categories at their true share', async () => {
  await ready()
  expect(within(donut()).getByText('$85.00')).toBeTruthy()
  expect(within(donut()).getByText('All categories')).toBeTruthy()
  expect(segment('Groceries, 52%, $60.00').getAttribute('aria-pressed')).toBe('false')
  expect(segment('Dining, 48%, $55.00').getAttribute('tabindex')).toBe('0')
  expect(within(donut()).queryByRole('button', { name: /Entertainment|Uncategorized/ })).toBeNull()
  expect(screen.getByText('2 at or below zero not drawn')).toBeTruthy()
  expect(donut().querySelector('button')).toBeNull()
  await click(metric('Card Benefits'))
  expect(within(donut('Card Benefits')).getByText('$45.00')).toBeTruthy()
  expect(within(donut('Card Benefits')).getByRole('button', { name: 'Entertainment, 56%, $25.00' })).toBeTruthy()
  expect(within(donut('Card Benefits')).getByRole('button', { name: 'Dining, 44%, $20.00' })).toBeTruthy()
})

test('a donut segment selects its category like the row, both ways, and clears on a second click', async () => {
  await ready()
  await click(segment(/^Dining,/))
  await screen.findByText('DINING gross 0')
  expect(latestDetails().searchParams.get('canonical_category')).toBe('DINING')
  expect(latestDetails().searchParams.get('spending_component')).toBe('net')
  expect(segment(/^Dining,/).getAttribute('aria-pressed')).toBe('true')
  expect(segment(/^Groceries,/).getAttribute('aria-pressed')).toBe('false')
  expect(within(row('Dining')).getByRole('button', { name: /^Net Spending transactions for Dining/ }).getAttribute('aria-pressed')).toBe('true')
  expect(within(donut()).getByText('Dining')).toBeTruthy()
  expect(within(donut()).getByText('$55.00')).toBeTruthy()
  expect(within(donut()).getByText('48% of Net Spending')).toBeTruthy()
  await click(segment(/^Dining,/))
  await waitFor(() => expect(screen.queryByText('DINING gross 0')).toBeNull())
  expect(segment(/^Dining,/).getAttribute('aria-pressed')).toBe('false')
  expect(within(donut()).getByText('All categories')).toBeTruthy()
  await click(row('Groceries'))
  await screen.findByText('GROCERIES gross 0')
  expect(segment(/^Groceries,/).getAttribute('aria-pressed')).toBe('true')
  expect(within(donut()).getByText('52% of Net Spending')).toBeTruthy()
  await click(row('Entertainment'))
  await screen.findByText('ENTERTAINMENT card_benefits 0')
  expect(segment(/^Groceries,/).getAttribute('aria-pressed')).toBe('false')
  expect(within(donut()).getByText('Not drawn')).toBeTruthy()
  expect(within(donut()).getByText('-$25.00')).toBeTruthy()
})

test('donut segments work from the keyboard and show the same details on focus as on hover', async () => {
  await ready()
  const dining = segment(/^Dining,/)
  await act(async () => { dining.focus() })
  expect(document.activeElement).toBe(dining)
  const tip = screen.getByRole('tooltip')
  expect(tip.textContent).toContain('$55.00')
  expect(tip.textContent).toContain('Dining, 48%')
  expect(detailRequests()).toHaveLength(0)
  await act(async () => { fireEvent.keyDown(dining, { key: 'Enter' }) })
  await screen.findByText('DINING gross 0')
  expect(segment(/^Dining,/).getAttribute('aria-pressed')).toBe('true')
  await act(async () => { fireEvent.keyDown(segment(/^Dining,/), { key: ' ' }) })
  await waitFor(() => expect(screen.queryByText('DINING gross 0')).toBeNull())
  await act(async () => { segment(/^Dining,/).blur() })
  expect(screen.queryByRole('tooltip')).toBeNull()
})


test('mobile label filtering uses ten rows and a full-filter net total across pages', async () => {
  width = 390
  const currentFetch = global.fetch
  global.fetch = jest.fn(async (input, init) => {
    const url = new URL(String(input), 'http://synthetic.test')
    if (!url.pathname.endsWith('/transactions')) return currentFetch(input, init)
    requests.push(url)
    const offset = Number(url.searchParams.get('offset'))
    const limit = Number(url.searchParams.get('limit'))
    return { ok: true, json: async () => ({ total: 21, component_totals: { net_spending: '113.00' },
      transactions: Array.from({ length: Math.min(limit, 21 - offset) }, (_, index) => ({
        transaction_id: `gear-${offset + index}`, transaction_date: '2026-09-01',
        institution_name: 'Synthetic', account_name: 'Card', merchant_name: `Equipment ${offset + index}`,
        amount: '-10.00', transaction_type: 'expense', effective_category: 'GENERAL_MERCHANDISE',
        automatic_labels: [], manual_label_decisions: { 'tech-id': 'include' }, effective_labels: ['tech-id', 'other-id'],
      })),
    }) } as Response
  })
  render(createElement(HomePage))
  await screen.findByRole('region', { name: 'Monthly financial summary' })
  await act(async () => { fireEvent.change(screen.getByRole('combobox', { name: 'Transaction label filter' }), { target: { value: 'tech-id' } }) })
  await screen.findByText('Equipment 0')
  expect(latestDetails().searchParams.get('label')).toBe('tech-id')
  expect(latestDetails().searchParams.get('limit')).toBe('10')
  expect(screen.queryByText('Equipment 10')).toBeNull()
  expect(screen.getByText('Net spending: $113.00')).toBeTruthy()
  await click(screen.getByRole('button', { name: 'Next' }))
  await screen.findByText('Equipment 10')
  expect(latestDetails().searchParams.get('offset')).toBe('10')
  expect(screen.getByText('Net spending: $113.00')).toBeTruthy()
  expect(screen.getByRole('option', { name: 'old gear (archived)' })).toBeTruthy()
})
