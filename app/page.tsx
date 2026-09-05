'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import AccountBadge from '@/components/account-badge'
import PlaidLinkButton from '@/components/plaid-link-button'

type Category = {
  category: string
  gross_spending: string
  refunds: string
  net_spending: string
  spending_transaction_count: number
  expense_transaction_count: number
  refund_transaction_count: number
}

type Monthly = {
  month: string
  gross_spending: string
  refunds: string
  card_benefits: string
  net_spending: string
  income: string
  net_savings: string
  unclassified_count: number
  category_breakdown: Category[]
}

type TrendMonth = { month: string; net_spending: string; income: string; net_savings: string }
type BreakdownGroup = {
  institution_id: string
  institution_name: string
  account_id?: string
  account_name?: string
  account_mask?: string | null
  account_type?: string
  account_subtype?: string | null
  gross_spending: string
  refunds: string
  card_benefits: string
  net_spending: string
}
type Detail = {
  transaction_id: string
  transaction_date: string
  institution_name: string | null
  account_name: string | null
  account_mask: string | null
  account_type: string | null
  account_subtype: string | null
  merchant_name: string | null
  description: string | null
  amount: string
  transaction_type: string
  plaid_category: string
}

function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-lg border bg-white shadow-sm ${className}`}>{children}</section>
}

function money(value: string) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value))
}

function currentMonth() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function MetricCard({ label, value, onClick }: { label: string; value: string; onClick?: () => void }) {
  return (
    <Card className={onClick ? 'cursor-pointer transition hover:border-slate-400' : ''}>
      <button type="button" onClick={onClick} className="w-full p-5 text-left" disabled={!onClick}>
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-bold">{value}</p>
      </button>
    </Card>
  )
}

export default function HomePage() {
  const [month, setMonth] = useState(currentMonth)
  const [monthly, setMonthly] = useState<Monthly | null>(null)
  const [trend, setTrend] = useState<TrendMonth[]>([])
  const [groupBy, setGroupBy] = useState<'institution' | 'account'>('institution')
  const [breakdown, setBreakdown] = useState<BreakdownGroup[]>([])
  const [categoryMode, setCategoryMode] = useState<'gross' | 'refunds'>('gross')
  const [detailFilter, setDetailFilter] = useState<{ category?: string; transactionType?: string } | null>(null)
  const [details, setDetails] = useState<Detail[]>([])
  const [detailTotal, setDetailTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadDashboard = useCallback(async () => {
    setLoading(true)
    setError('')
    setDetailFilter(null)
    try {
      const [monthlyResponse, trendResponse, breakdownResponse] = await Promise.all([
        fetch(`/api/pft/analytics/monthly?month=${month}`),
        fetch(`/api/pft/analytics/trend?end_month=${month}`),
        fetch(`/api/pft/analytics/breakdown?month=${month}&group_by=${groupBy}`),
      ])
      if (!monthlyResponse.ok || !trendResponse.ok || !breakdownResponse.ok) throw new Error('request failed')
      const [monthlyData, trendData, breakdownData] = await Promise.all([
        monthlyResponse.json(), trendResponse.json(), breakdownResponse.json(),
      ])
      setMonthly(monthlyData)
      setTrend(trendData.months || [])
      setBreakdown(breakdownData.groups || [])
    } catch {
      setError('Analytics could not be loaded. Confirm the local API is running.')
    } finally {
      setLoading(false)
    }
  }, [month, groupBy])

  useEffect(() => { void loadDashboard() }, [loadDashboard])

  useEffect(() => {
    if (!detailFilter) return
    const parameters = new URLSearchParams({ month, limit: '100' })
    if (detailFilter.category) parameters.set('category', detailFilter.category)
    if (detailFilter.transactionType) parameters.set('transaction_type', detailFilter.transactionType)
    fetch(`/api/pft/analytics/transactions?${parameters}`)
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((data) => {
        setDetails(data.transactions || [])
        setDetailTotal(data.total || 0)
      })
      .catch(() => setError('Transaction details could not be loaded.'))
  }, [detailFilter, month])

  const chartData = useMemo(() => trend.map((value) => ({
    month: value.month.slice(5),
    netSpending: Number(value.net_spending),
    income: Number(value.income),
    netSavings: Number(value.net_savings),
  })), [trend])
  const categories = useMemo(() => {
    const included = (monthly?.category_breakdown || []).filter((category) => (
      categoryMode === 'gross'
        ? category.expense_transaction_count > 0
        : category.refund_transaction_count > 0
    ))
    return [...included].sort((a, b) => (
      categoryMode === 'gross'
        ? Number(b.gross_spending) - Number(a.gross_spending)
        : Number(b.refunds) - Number(a.refunds)
    ))
  }, [monthly, categoryMode])

  function selectCategoryMode(mode: 'gross' | 'refunds') {
    setCategoryMode(mode)
    setDetailFilter(null)
    setDetails([])
    setDetailTotal(0)
  }

  return (
    <main className="container mx-auto max-w-7xl px-4 py-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold tracking-tight">Personal Finance Tracker</h1>
          <p className="mt-2 text-muted-foreground">Effective spending and savings across active institutions.</p>
          <Link className="mt-2 inline-block text-sm font-medium text-blue-700 underline" href="/review">
            Review ambiguous transactions{monthly ? ` (${monthly.unclassified_count})` : ''}
          </Link>
        </div>
        <label className="text-sm font-medium">
          Month
          <input
            className="ml-3 rounded-md border bg-white px-3 py-2"
            type="month"
            value={month}
            onChange={(event) => setMonth(event.target.value)}
          />
        </label>
      </header>

      {error && <p role="alert" className="mt-6 rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {loading && <p className="mt-8 text-muted-foreground">Loading analytics…</p>}

      {monthly && !loading && (
        <>
          <section className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard label="Net Spending" value={money(monthly.net_spending)} />
            <MetricCard label="Gross Spending" value={money(monthly.gross_spending)} onClick={() => selectCategoryMode('gross')} />
            <MetricCard label="Income" value={money(monthly.income)} onClick={() => setDetailFilter({ transactionType: 'income' })} />
            <MetricCard label="Net Savings" value={money(monthly.net_savings)} />
            <MetricCard label="Refunds" value={money(monthly.refunds)} onClick={() => selectCategoryMode('refunds')} />
            <MetricCard label="Card Benefits" value={money(monthly.card_benefits)} />
            <MetricCard label="Needs Review" value={String(monthly.unclassified_count)} onClick={() => setDetailFilter({ transactionType: 'unclassified' })} />
          </section>

          <section className="mt-8 grid gap-6 lg:grid-cols-2">
            <Card className="p-5">
              <h2 className="text-lg font-semibold">12-Month Trend</h2>
              <div className="mt-4 h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData} margin={{ left: 12, right: 12 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="month" />
                    <YAxis tickFormatter={(value) => `$${value}`} />
                    <Tooltip formatter={(value) => money(String(value))} />
                    <Legend />
                    <Line type="monotone" dataKey="netSpending" name="Net Spending" stroke="#dc2626" />
                    <Line type="monotone" dataKey="income" name="Income" stroke="#16a34a" />
                    <Line type="monotone" dataKey="netSavings" name="Net Savings" stroke="#2563eb" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <Card className="overflow-hidden">
              <div className="p-5">
                <h2 className="text-lg font-semibold">
                  {categoryMode === 'gross' ? 'Gross Spending by Category' : 'Refunds by Category'}
                </h2>
                <p className="text-xs text-muted-foreground">Card benefits are not allocated to categories.</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="p-3">Category</th>
                      <th>{categoryMode === 'gross' ? 'Gross' : 'Refunds'}</th>
                      <th>Transactions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {categories.map((category) => (
                      <tr
                        key={category.category}
                        className="cursor-pointer border-t hover:bg-slate-50"
                        onClick={() => setDetailFilter({
                          category: category.category,
                          transactionType: categoryMode === 'gross' ? 'expense' : 'refund',
                        })}
                      >
                        <td className="p-3 font-medium">{category.category.replace(/_/g, ' ')}</td>
                        <td>{money(categoryMode === 'gross' ? category.gross_spending : category.refunds)}</td>
                        <td>{categoryMode === 'gross' ? category.expense_transaction_count : category.refund_transaction_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </section>

          <Card className="mt-6 overflow-hidden">
            <div className="flex items-center justify-between p-5">
              <h2 className="text-lg font-semibold">Spending by {groupBy}</h2>
              <select className="rounded-md border px-3 py-2 text-sm" value={groupBy} onChange={(event) => setGroupBy(event.target.value as 'institution' | 'account')}>
                <option value="institution">Institution</option><option value="account">Account</option>
              </select>
            </div>
            <div className="grid gap-3 border-t p-5 md:grid-cols-2 lg:grid-cols-4">
              {breakdown.map((group) => (
                <div key={group.account_id || group.institution_id} className="rounded-md border p-4">
                  {group.account_name ? (
                    <AccountBadge institutionName={group.institution_name} accountName={group.account_name} accountMask={group.account_mask || null} accountType={group.account_type || ''} accountSubtype={group.account_subtype} />
                  ) : <p className="font-semibold">{group.institution_name}</p>}
                  <p className="mt-3 text-xl font-bold">{money(group.net_spending)}</p>
                  <p className="text-xs text-muted-foreground">net spending</p>
                </div>
              ))}
            </div>
          </Card>

          {detailFilter && (
            <Card className="mt-6 overflow-hidden">
              <div className="flex items-start justify-between p-5">
                <div><h2 className="text-lg font-semibold">Transaction Details</h2><p className="text-sm text-muted-foreground">{detailTotal} matching transactions</p></div>
                <button type="button" className="text-sm text-blue-700 underline" onClick={() => setDetailFilter(null)}>Close</button>
              </div>
              <div className="divide-y">
                {details.map((detail) => (
                  <div key={detail.transaction_id} className="flex flex-wrap items-center justify-between gap-3 p-4">
                    <div>
                      <p className="font-medium">{detail.merchant_name || detail.description || 'Unknown transaction'}</p>
                      <p className="text-sm text-muted-foreground">{detail.transaction_date} · {detail.description} · {detail.transaction_type.replace(/_/g, ' ')}</p>
                      {detail.institution_name && detail.account_name && (
                        <div className="mt-2"><AccountBadge institutionName={detail.institution_name} accountName={detail.account_name} accountMask={detail.account_mask} accountType={detail.account_type || ''} accountSubtype={detail.account_subtype} /></div>
                      )}
                    </div>
                    <p className="font-semibold">{money(detail.amount)}</p>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}

      <Card className="mt-8 p-5">
        <h2 className="font-semibold">Connected Institutions</h2>
        <div className="mt-3"><PlaidLinkButton /></div>
      </Card>
    </main>
  )
}
