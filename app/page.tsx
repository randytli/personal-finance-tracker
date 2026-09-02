'use client'

import { useState, useEffect, type ReactNode } from 'react'
import { DollarSign, TrendingDown, Calendar, PieChart } from 'lucide-react'
import PlaidLinkButton from '@/components/plaid-link-button'
import Link from 'next/link'

function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-lg border bg-white shadow-sm ${className}`}>{children}</section>
}

function CardHeader({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`p-6 ${className}`}>{children}</div>
}

function CardTitle({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <h2 className={`font-semibold ${className}`}>{children}</h2>
}

function CardDescription({ children }: { children: ReactNode }) {
  return <p className="mt-1 text-sm text-muted-foreground">{children}</p>
}

function CardContent({ children }: { children: ReactNode }) {
  return <div className="px-6 pb-6">{children}</div>
}

export default function HomePage() {
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    // Simulate loading
    setTimeout(() => setIsLoading(false), 1000)
  }, [])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-primary"></div>
      </div>
    )
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-4xl font-bold tracking-tight">Personal Finance Tracker</h1>
        <p className="text-muted-foreground mt-2">
          Track your spending, categorize transactions, and gain insights into your financial habits.
        </p>
        <Link className="mt-3 inline-block text-sm font-medium text-blue-700 underline" href="/review">
          Review ambiguous transactions
        </Link>
      </div>

      {/* Quick Stats */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-8">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Spent This Month</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">$2,847.32</div>
            <p className="text-xs text-muted-foreground">
              +12% from last month
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Transactions</CardTitle>
            <TrendingDown className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">127</div>
            <p className="text-xs text-muted-foreground">
              +8 from yesterday
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Categories</CardTitle>
            <PieChart className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">8</div>
            <p className="text-xs text-muted-foreground">
              Active spending categories
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Last Updated</CardTitle>
            <Calendar className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">2h ago</div>
            <p className="text-xs text-muted-foreground">
              Sync with Plaid
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Main Content */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Monthly Spending Overview</CardTitle>
            <CardDescription>
              Your spending patterns for the current month
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[300px] flex items-center justify-center text-muted-foreground">
              Chart will be implemented here
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent Transactions</CardTitle>
            <CardDescription>
              Latest transactions from your connected accounts
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">Starbucks Coffee</p>
                  <p className="text-sm text-muted-foreground">Food & Dining</p>
                </div>
                <div className="text-right">
                  <p className="font-medium">-$4.85</p>
                  <p className="text-sm text-muted-foreground">Today</p>
                </div>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">Grocery Store</p>
                  <p className="text-sm text-muted-foreground">Groceries</p>
                </div>
                <div className="text-right">
                  <p className="font-medium">-$67.23</p>
                  <p className="text-sm text-muted-foreground">Yesterday</p>
                </div>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">Credit Card Payment</p>
                  <p className="text-sm text-muted-foreground">Transfer</p>
                </div>
                <div className="text-right">
                  <p className="font-medium">-$500.00</p>
                  <p className="text-sm text-muted-foreground">2 days ago</p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Connect Bank Account CTA */}
      <Card className="mt-8">
        <CardHeader>
          <CardTitle>Connect Your Bank Account</CardTitle>
          <CardDescription>
            Securely link your bank accounts via Plaid to start tracking your transactions
          </CardDescription>
        </CardHeader>
        <CardContent>
          <PlaidLinkButton />
        </CardContent>
      </Card>
    </div>
  )
}
