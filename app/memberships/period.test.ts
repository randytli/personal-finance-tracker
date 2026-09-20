import {
  membershipPeriods, membershipRangeText, membershipSummaryMatches,
  membershipSummaryPath, membershipTransactionsPath,
} from './period'

describe('Membership reporting periods', () => {
  test('offers trailing 12 months first and YTD second', () => {
    expect(membershipPeriods).toEqual([
      { value: 'trailing_12m', label: 'Trailing 12 months' },
      { value: 'ytd', label: 'YTD' },
    ])
  })

  test('sends the selected period with the ending month', () => {
    expect(membershipSummaryPath('2026-09', 'trailing_12m'))
      .toBe('/api/pft/analytics/memberships?end_month=2026-09&period=trailing_12m')
    expect(membershipSummaryPath('2026-09', 'ytd'))
      .toBe('/api/pft/analytics/memberships?end_month=2026-09&period=ytd')
    expect(membershipRangeText('2025-10', '2026-09', 'trailing_12m'))
      .toBe('2025-10 through 2026-09 · Trailing 12 months')
    expect(membershipRangeText('2026-01', '2026-09', 'ytd'))
      .toBe('2026-01 through 2026-09 · YTD')
  })

  test('rejects stale summary state and uses period bounds for paginated details', () => {
    const trailing = { period: 'trailing_12m' as const, end_month: '2026-09' }
    expect(membershipSummaryMatches(trailing, '2026-09', 'ytd')).toBe(false)
    expect(membershipSummaryMatches(trailing, '2026-08', 'trailing_12m')).toBe(false)
    expect(membershipSummaryMatches(trailing, '2026-09', 'trailing_12m')).toBe(true)

    const ytd = new URL(membershipTransactionsPath('2026-01', '2026-09', 'card', 50, 50),
      'https://example.test')
    expect(Object.fromEntries(ytd.searchParams)).toEqual({
      start_month: '2026-01', end_month: '2026-09', label: 'MEMBERSHIP',
      limit: '50', offset: '50', membership_view: 'all', account_id: 'card',
    })
    const trailingDetails = new URL(
      membershipTransactionsPath('2025-10', '2026-09', null, 0, 50), 'https://example.test')
    expect(trailingDetails.searchParams.get('start_month')).toBe('2025-10')
    expect(trailingDetails.searchParams.has('account_id')).toBe(false)
    expect(trailingDetails.searchParams.get('membership_view')).toBe('all')
    const reimbursements = new URL(
      membershipTransactionsPath('2026-01', '2026-09', 'receiving-account', 50, 50, 'reimbursements'),
      'https://example.test')
    expect(reimbursements.searchParams.get('membership_view')).toBe('reimbursements')
    expect(reimbursements.searchParams.get('account_id')).toBe('receiving-account')
    expect(reimbursements.searchParams.get('offset')).toBe('50')
  })
})
