export type MembershipPeriod = 'trailing_12m' | 'ytd'

export const membershipPeriods: ReadonlyArray<{ value: MembershipPeriod; label: string }> = [
  { value: 'trailing_12m', label: 'Trailing 12 months' },
  { value: 'ytd', label: 'YTD' },
]

export function membershipSummaryPath(endMonth: string, period: MembershipPeriod) {
  const parameters = new URLSearchParams({ end_month: endMonth, period })
  return '/api/pft/analytics/memberships?' + parameters.toString()
}

export function membershipTransactionsPath(
  startMonth: string,
  endMonth: string,
  accountId: string | null,
  offset: number,
  limit: number,
) {
  const parameters = new URLSearchParams({
    start_month: startMonth,
    end_month: endMonth,
    label: 'MEMBERSHIP',
    limit: String(limit),
    offset: String(offset),
  })
  if (accountId) parameters.set('account_id', accountId)
  return '/api/pft/analytics/transactions?' + parameters.toString()
}

export function membershipRangeText(startMonth: string, endMonth: string, period: MembershipPeriod) {
  const label = membershipPeriods.find(option => option.value === period)?.label ?? period
  return startMonth + ' through ' + endMonth + ' · ' + label
}

export function membershipSummaryMatches(
  summary: { end_month: string; period: MembershipPeriod } | null,
  endMonth: string,
  period: MembershipPeriod,
) {
  return summary?.end_month === endMonth && summary.period === period
}
