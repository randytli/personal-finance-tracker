'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import AccountBadge from '@/components/account-badge'

const TYPES = ['expense', 'refund', 'income', 'card_benefit', 'payment', 'transfer', 'adjustment'] as const
type TransactionType = typeof TYPES[number]

type ReviewTransaction = {
  transaction_id: string
  transaction_date: string
  institution_name: string
  account_name: string
  account_mask: string | null
  account_type: string
  merchant_name: string | null
  description: string | null
  amount: string
  plaid_category: string | null
}

type Undo = { transaction: ReviewTransaction; transactionType: TransactionType }

export default function ReviewPage() {
  const [transactions, setTransactions] = useState<ReviewTransaction[]>([])
  const [total, setTotal] = useState(0)
  const [choices, setChoices] = useState<Record<string, TransactionType>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [undo, setUndo] = useState<Undo | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await fetch('/api/pft/review/transactions')
      if (!response.ok) throw new Error('load failed')
      const data = await response.json()
      setTransactions(Array.isArray(data.transactions) ? data.transactions : [])
      setTotal(typeof data.total === 'number' ? data.total : 0)
    } catch {
      setError('Transactions needing review could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function save(transaction: ReviewTransaction) {
    const transactionType = choices[transaction.transaction_id]
    if (!transactionType) {
      setError('Choose a classification before saving.')
      return
    }
    setBusy(transaction.transaction_id)
    setError('')
    try {
      const response = await fetch(
        `/api/pft/review/transactions/${encodeURIComponent(transaction.transaction_id)}/override`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ transaction_type: transactionType }),
        },
      )
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail || 'save failed')
      }
      setTransactions((current) => current.filter((row) => row.transaction_id !== transaction.transaction_id))
      setTotal((current) => Math.max(0, current - 1))
      setUndo({ transaction, transactionType })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Classification could not be saved.')
    } finally {
      setBusy(null)
    }
  }

  async function undoLast() {
    if (!undo) return
    setBusy(undo.transaction.transaction_id)
    setError('')
    try {
      const response = await fetch(
        `/api/pft/review/transactions/${encodeURIComponent(undo.transaction.transaction_id)}/override`,
        { method: 'DELETE' },
      )
      if (!response.ok) throw new Error('Undo could not be saved.')
      setUndo(null)
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Undo could not be saved.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <main className="container mx-auto max-w-5xl px-4 py-8">
      <Link href="/" className="text-sm text-blue-700 underline">Back to overview</Link>
      <div className="mt-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold">Needs Review</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Classify ambiguous transactions without changing automatic rules.
          </p>
        </div>
        <p className="text-sm font-medium">{total} remaining</p>
      </div>

      {undo && (
        <div className="mt-5 rounded-md border bg-white p-4 text-sm">
          Saved {undo.transactionType.replace('_', ' ')} for {undo.transaction.description || undo.transaction.merchant_name || 'transaction'}.
          <button className="ml-3 font-medium text-blue-700 underline" onClick={undoLast} disabled={busy !== null}>Undo</button>
        </div>
      )}
      {error && <p role="alert" className="mt-5 rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {loading && <p className="mt-8 text-muted-foreground">Loading transactions…</p>}
      {!loading && transactions.length === 0 && !error && (
        <p className="mt-8 rounded-lg border bg-white p-8 text-center">Nothing needs review.</p>
      )}

      <div className="mt-6 space-y-4">
        {transactions.map((transaction) => (
          <article key={transaction.transaction_id} className="rounded-lg border bg-white p-5 shadow-sm">
            <div className="flex flex-wrap justify-between gap-3">
              <div>
                <AccountBadge
                  institutionName={transaction.institution_name}
                  accountName={transaction.account_name}
                  accountMask={transaction.account_mask}
                  accountType={transaction.account_type}
                />
                <h2 className="mt-2 font-semibold">{transaction.merchant_name || transaction.description || 'Unknown transaction'}</h2>
                <p className="text-sm text-muted-foreground">{transaction.description}</p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {transaction.transaction_date} · {transaction.institution_name} · {transaction.account_name} · {transaction.account_type}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">Plaid category: {transaction.plaid_category || 'Uncategorized'}</p>
              </div>
              <p className="text-lg font-semibold">{transaction.amount}</p>
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <select
                aria-label={`Classification for ${transaction.description || transaction.transaction_id}`}
                className="rounded-md border px-3 py-2 text-sm"
                value={choices[transaction.transaction_id] || ''}
                onChange={(event) => setChoices((current) => ({
                  ...current,
                  [transaction.transaction_id]: event.target.value as TransactionType,
                }))}
              >
                <option value="">Choose classification</option>
                {TYPES.map((type) => <option key={type} value={type}>{type.replace('_', ' ')}</option>)}
              </select>
              <button
                className="rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                disabled={busy !== null || !choices[transaction.transaction_id]}
                onClick={() => save(transaction)}
              >
                {busy === transaction.transaction_id ? 'Saving…' : 'Save'}
              </button>
            </div>
          </article>
        ))}
      </div>
    </main>
  )
}
