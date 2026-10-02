'use client'

import { useEffect, useState } from 'react'
import { CircleAlert, CircleCheck, CircleX } from 'lucide-react'
import { GroupLabel, LoadingState, TransactionTypeBadge } from '@/components/page-presentation'
import { CategoryBadge } from '@/components/category-display'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

export type LifecycleStatus = 'pending' | 'active' | 'deactivated' | 'disabled'
export type LifecycleKind = 'activate' | 'deactivate'

export type ActivationCheck = { id: string; label: string; result: 'pass' | 'warn' | 'fail'; detail: string }

type Classification = { transaction_type: string | null; is_spending: boolean | null; is_internal_transfer: boolean | null; category: string }
type LedgerTransaction = Classification & {
  transaction_id: string; institution_name: string; account_name: string; transaction_date: string
  month: string; amount: string; merchant_name: string | null; description: string | null
}
type ChangedTransaction = Omit<LedgerTransaction, keyof Classification> & { before: Classification; after: Classification }
type Delta = { before: string; after: string; delta: string }

export type ImpactPreview = {
  item_id: string
  digest: string
  summary_by_month: Array<{ month: string; metrics: Record<string, Delta>; categories: Array<{ category: string } & Delta> }>
  new_transactions: LedgerTransaction[]
  removed_transactions: LedgerTransaction[]
  changed_existing_transactions: ChangedTransaction[]
}

export const STATUS_LABELS: Record<LifecycleStatus, string> = {
  pending: 'Pending review', active: 'Active', deactivated: 'Deactivated', disabled: 'Rejected',
}

export const STATUS_VARIANTS: Record<LifecycleStatus, 'warning' | 'success' | 'muted' | 'destructive'> = {
  pending: 'warning', active: 'success', deactivated: 'muted', disabled: 'destructive',
}

const METRIC_LABELS: Record<string, string> = {
  gross_spending: 'Gross spending', refunds: 'Refunds', reimbursements: 'Reimbursements',
  card_benefits: 'Card benefits', net_spending: 'Net spending', income: 'Income',
  net_savings: 'Net savings', unclassified_count: 'Unclassified',
}

export function money(value: string) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value))
}

function signedMoney(value: string) {
  const amount = Number(value)
  return `${amount > 0 ? '+' : ''}${money(value)}`
}

// Activation needs passing checks; deactivation is available to any active Item.
export function availableTransition(status: LifecycleStatus): LifecycleKind | null {
  if (status === 'active') return 'deactivate'
  if (status === 'pending' || status === 'deactivated') return 'activate'
  return null
}

export function checksAllowActivation(checks: ActivationCheck[] | null) {
  return checks !== null && checks.length > 0 && checks.every(check => check.result !== 'fail')
}

export function impactIsEmpty(preview: ImpactPreview) {
  return preview.summary_by_month.length === 0 && preview.new_transactions.length === 0
    && preview.removed_transactions.length === 0 && preview.changed_existing_transactions.length === 0
}

async function errorDetail(response: Response) {
  const body = await response.json().catch(() => null)
  const detail = body?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return `${detail.message}${detail.checks ? ` (${detail.checks.join(', ')})` : ''}`
  return `Request failed (${response.status})`
}

const CHECK_ICONS = { pass: CircleCheck, warn: CircleAlert, fail: CircleX }
const CHECK_TONES = { pass: 'text-success', warn: 'text-warning', fail: 'text-destructive' }

export function ActivationChecks({ checks }: { checks: ActivationCheck[] }) {
  return <ul aria-label="Pre-activation checks" className="flex flex-col divide-y">
    {checks.map(check => {
      const Icon = CHECK_ICONS[check.result]
      return <li key={check.id} className="flex items-start gap-3 px-4 py-3 sm:px-5">
        <Icon aria-hidden="true" className={cn('mt-0.5 size-[18px] shrink-0', CHECK_TONES[check.result])} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{check.label}
            <span className="sr-only">: {check.result === 'pass' ? 'passed' : check.result === 'warn' ? 'warning' : 'failed'}</span>
          </p>
          <p className="text-[13px] text-muted-foreground [overflow-wrap:anywhere]">{check.detail}</p>
        </div>
        <span className="shrink-0 text-[11px] font-bold uppercase tracking-[0.04em] text-muted-foreground">{check.id}</span>
      </li>
    })}
  </ul>
}

function ClassificationLine({ value }: { value: Classification }) {
  return <span className="flex flex-wrap items-center gap-1.5">
    <TransactionTypeBadge type={value.transaction_type} />
    {value.is_internal_transfer && <Badge variant="muted">Internal transfer</Badge>}
    <CategoryBadge category={value.category} />
  </span>
}

export function ImpactSummary({ preview }: { preview: ImpactPreview }) {
  if (impactIsEmpty(preview)) {
    return <Alert variant="success"><CircleCheck aria-hidden="true" />
      <p className="text-sm">No change: analytics and every published classification stay exactly the same.</p>
    </Alert>
  }
  return <div className="flex flex-col gap-5">
    <dl className="grid grid-cols-3 gap-2 text-center">
      {[['New transactions', preview.new_transactions.length],
        ['Existing reclassified', preview.changed_existing_transactions.length],
        ['Months changed', preview.summary_by_month.length]].map(([label, value]) =>
        <div key={label} className="rounded-xl bg-muted/60 px-2 py-2.5">
          <dt className="text-[11px] font-semibold text-muted-foreground">{label}</dt>
          <dd className="text-lg font-semibold tabular-nums">{value}</dd>
        </div>)}
    </dl>

    {preview.summary_by_month.length > 0 && <section aria-labelledby="impact-months">
      <GroupLabel id="impact-months">By month</GroupLabel>
      <ol className="mt-2 flex flex-col divide-y rounded-xl border">
        {preview.summary_by_month.map(month => <li key={month.month} className="px-3 py-2.5 text-sm">
          <p className="font-medium tabular-nums">{month.month}</p>
          <dl className="mt-1.5 grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
            {Object.entries(month.metrics).map(([name, delta]) => <div key={name} className="min-w-0">
              <dt className="text-xs text-muted-foreground">{METRIC_LABELS[name] || name}</dt>
              <dd className="flex flex-wrap items-baseline gap-x-1">
                {name === 'unclassified_count' ? <span className="money">{delta.before} → {delta.after}</span> : <>
                  <span className="money">{money(delta.before)} → {money(delta.after)}</span>
                  <span className="money text-xs text-muted-foreground">({signedMoney(delta.delta)})</span></>}
              </dd>
            </div>)}
          </dl>
          {month.categories.length > 0 && <ul aria-label={`${month.month} category net changes`} className="mt-2 flex flex-col gap-1">
            {month.categories.map(category => <li key={category.category} className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
              <CategoryBadge category={category.category} />
              <span className="flex flex-wrap justify-end gap-x-1 text-muted-foreground">
                <span className="money">{money(category.before)} → {money(category.after)}</span>
                <span className="money">({signedMoney(category.delta)})</span>
              </span>
            </li>)}
          </ul>}
        </li>)}
      </ol>
    </section>}

    {preview.changed_existing_transactions.length > 0 && <section aria-labelledby="impact-changed">
      <GroupLabel id="impact-changed">Existing transactions that change</GroupLabel>
      <ul className="mt-2 flex flex-col divide-y rounded-xl border">
        {preview.changed_existing_transactions.map(row => <li key={row.transaction_id} className="flex flex-col gap-1.5 px-3 py-2.5 text-sm">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="min-w-0 font-medium [overflow-wrap:anywhere]">{row.merchant_name || row.description || row.transaction_id}</span>
            <span className="money font-semibold">{money(row.amount)}</span>
          </div>
          <p className="text-[13px] text-muted-foreground">{row.transaction_date} · {row.institution_name} · {row.account_name}</p>
          <div className="grid gap-1 text-[13px] sm:grid-cols-[auto_minmax(0,1fr)] sm:gap-x-3">
            <span className="text-muted-foreground">Before</span><ClassificationLine value={row.before} />
            <span className="text-muted-foreground">After</span><ClassificationLine value={row.after} />
          </div>
        </li>)}
      </ul>
    </section>}

    {preview.removed_transactions.length > 0 && <Alert variant="warning"><CircleAlert aria-hidden="true" />
      <p className="text-sm">{preview.removed_transactions.length} transactions would leave the ledger.</p>
    </Alert>}
  </div>
}

const COPY: Record<LifecycleKind, { title: string; confirm: string; description: string }> = {
  activate: {
    title: 'Activate institution',
    confirm: 'Confirm activation',
    description: 'Activation publishes this institution: its transactions enter analytics and classification, and scheduled sync starts. This preview compares the whole ledger before and after.',
  },
  deactivate: {
    title: 'Deactivate institution',
    confirm: 'Confirm deactivation',
    description: 'Deactivation stops syncing this institution. Its transactions stay in analytics and classification; the saved cursor is kept so reactivation resumes where sync stopped.',
  },
}

// The preview runs when the dialog opens; nothing is committed until the confirm button is pressed.
export function LifecycleDialog({ itemId, institutionName, kind, open, onOpenChange, onDone }: {
  itemId: string; institutionName: string; kind: LifecycleKind; open: boolean
  onOpenChange: (open: boolean) => void; onDone: () => void
}) {
  const [preview, setPreview] = useState<ImpactPreview | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const base = `/api/pft/plaid/items/${encodeURIComponent(itemId)}`

  useEffect(() => {
    if (!open) return
    let active = true
    setPreview(null)
    setError('')
    fetch(`${base}/${kind === 'activate' ? 'activation' : 'deactivation'}-preview`, { method: 'POST' })
      .then(async response => response.ok ? response.json() : Promise.reject(new Error(await errorDetail(response))))
      .then(data => { if (active) setPreview(data) })
      .catch((reason: Error) => { if (active) setError(reason.message || 'The impact preview could not be loaded.') })
    return () => { active = false }
  }, [base, kind, open])

  async function confirm() {
    if (!preview) return
    setSubmitting(true)
    setError('')
    try {
      const response = await fetch(`${base}/${kind}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preview_digest: preview.digest }),
      })
      if (!response.ok) throw new Error(await errorDetail(response))
      onOpenChange(false)
      onDone()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The change was not applied.')
    } finally {
      setSubmitting(false)
    }
  }

  const copy = COPY[kind]
  return <Dialog open={open} onOpenChange={next => { if (!submitting) onOpenChange(next) }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{copy.title}: {institutionName}</DialogTitle>
        <DialogDescription>{copy.description}</DialogDescription>
      </DialogHeader>
      {!preview && !error && <LoadingState label="Calculating impact preview" rows={2} />}
      {error && <Alert variant="destructive" role="alert"><CircleX aria-hidden="true" /><p className="text-sm">{error}</p></Alert>}
      {preview && <ImpactSummary preview={preview} />}
      <DialogFooter>
        <Button variant="outline" disabled={submitting} onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant={kind === 'deactivate' ? 'destructive' : 'default'} disabled={!preview || submitting}
          onClick={confirm}>{submitting ? 'Applying…' : copy.confirm}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}
