'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { CircleAlert, CircleCheck, CircleDashed } from 'lucide-react'
import AccountBadge from '@/components/account-badge'
import InstitutionBadge from '@/components/institution-badge'
import {
  ActivationChecks, LifecycleDialog, OnboardingDialog, STATUS_LABELS, STATUS_VARIANTS, availableTransition,
  checksAllowActivation, money, type ActivationCheck, type LifecycleKind, type LifecycleStatus, type OnboardingKind,
} from '@/components/institution-lifecycle'
import {
  Amount, DayGroup, LoadingState, PageHeader, PageNavigation, Pagination, SectionCard, SectionHeader,
  TransactionRow, TransactionTypeBadge, groupByDay, pageClassName, useTransactionPageSize,
} from '@/components/page-presentation'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type ItemAccount = {
  account_id: string; name: string; mask: string | null; type: string; subtype: string | null
  consumer_transactions_enabled: boolean; transaction_count: number
}

type ItemDetail = {
  item_id: string; institution_name: string; status: LifecycleStatus; sync_enabled: boolean; published: boolean
  activated_at: string | null; deactivated_at: string | null; has_cursor: boolean; sync_paused: boolean
  last_sync_success_at: string | null; metadata_warning: string | null; accounts: ItemAccount[]
  raw_transaction_count: number; normalized_transaction_count: number
}

type PreviewTransaction = {
  transaction_id: string; account_name: string; transaction_date: string; amount: string
  merchant_name: string | null; description: string | null; plaid_category: string | null
  transaction_type: string | null
}

async function json<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(String(response.status))
  return response.json()
}

function ReviewStep({ done, title, detail }: { done: boolean; title: string; detail: string }) {
  const Icon = done ? CircleCheck : CircleDashed
  return <li className="flex items-start gap-3 px-4 py-3 sm:px-5">
    <Icon aria-hidden="true" className={cn('mt-0.5 size-[18px] shrink-0', done ? 'text-success' : 'text-muted-foreground')} />
    <div className="min-w-0">
      <p className="text-sm font-medium">{title}<span className="sr-only">: {done ? 'done' : 'not done'}</span></p>
      <p className="text-[13px] text-muted-foreground">{detail}</p>
    </div>
  </li>
}

export default function InstitutionItemPage() {
  const params = useParams<{ item_id: string }>()
  const itemId = decodeURIComponent(String(params.item_id))
  const base = `/api/pft/plaid/items/${encodeURIComponent(itemId)}`
  const pageSize = useTransactionPageSize()
  const [item, setItem] = useState<ItemDetail | null>(null)
  const [checks, setChecks] = useState<ActivationCheck[] | null>(null)
  const [transactions, setTransactions] = useState<PreviewTransaction[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [dialog, setDialog] = useState<LifecycleKind | null>(null)
  const [onboarding, setOnboarding] = useState<OnboardingKind | null>(null)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let active = true
    setError('')
    json<ItemDetail>(base).then(data => {
      if (!active) return
      setItem(data)
      if (data.status === 'pending' || data.status === 'deactivated') {
        json<{ checks: ActivationCheck[] }>(`${base}/activation-checks`)
          .then(result => { if (active) setChecks(result.checks) })
          .catch(() => { if (active) setError('Pre-activation checks could not be loaded.') })
      } else {
        setChecks(null)
      }
    }).catch(() => { if (active) setError('This institution could not be loaded.') })
    return () => { active = false }
  }, [base, reload])

  useEffect(() => {
    let active = true
    json<{ transactions: PreviewTransaction[]; total: number }>(
      `${base}/transactions-preview?limit=${pageSize}&offset=${offset}`)
      .then(data => { if (active) { setTransactions(data.transactions); setTotal(data.total) } })
      .catch(() => { if (active) setError('The transaction preview could not be loaded.') })
    return () => { active = false }
  }, [base, offset, pageSize, reload])

  const done = useCallback((kind: LifecycleKind) => {
    setNotice(kind === 'deactivate' ? 'Institution deactivated. Its transactions stay in analytics.'
      : kind === 'reactivate' ? 'Institution reactivated.' : 'Institution activated.')
    setChecks(null)
    setReload(value => value + 1)
  }, [])

  const onboardingDone = useCallback((kind: OnboardingKind) => {
    setNotice(kind === 'reject' ? 'Onboarding cancelled. The institution is rejected and its staged data stays unpublished.'
      : 'Onboarding retried. The institution is pending again; nothing was imported, normalized or published.')
    setChecks(null)
    setReload(value => value + 1)
  }, [])

  const transition = item ? availableTransition(item.status) : null
  const onboardingAction: OnboardingKind | null = item?.status === 'pending' ? 'reject'
    : item?.status === 'disabled' ? 'retry-onboarding' : null
  const activationBlocked = (transition === 'activate' || transition === 'reactivate') && !checksAllowActivation(checks)
  const enabledAccounts = item?.accounts.filter(account => account.consumer_transactions_enabled).length ?? 0

  return <div className="pft-app">
    <PageNavigation />
    <main className={pageClassName}>
      <PageHeader
        title={item ? item.institution_name : 'Institution'}
        description={item ? (item.published ? 'Published: counted in analytics and classification.' : 'Not published: absent from analytics and published classification.') : undefined}
        meta={item && <div className="mt-2 flex flex-wrap items-center gap-2">
          <InstitutionBadge institutionName={item.institution_name} />
          <Badge variant={STATUS_VARIANTS[item.status]}>{STATUS_LABELS[item.status]}</Badge>
          <Badge variant="muted">{item.sync_enabled ? 'Sync on' : 'Sync off'}</Badge>
        </div>}
        actions={(transition || onboardingAction) && <>
          {onboardingAction && <Button variant={onboardingAction === 'reject' ? 'ghost' : 'default'}
            onClick={() => { setNotice(''); setOnboarding(onboardingAction) }}>
            {onboardingAction === 'reject' ? 'Cancel onboarding' : 'Retry onboarding'}
          </Button>}
          {transition && <Button variant={transition === 'deactivate' ? 'outline' : 'default'}
            disabled={activationBlocked} onClick={() => { setNotice(''); setDialog(transition) }}>
            {transition === 'deactivate' ? 'Deactivate' : transition === 'reactivate' ? 'Reactivate' : 'Activate'}
          </Button>}
        </>} />

      {error && <Alert variant="destructive" role="alert" className="mt-4"><CircleAlert aria-hidden="true" />
        <div className="flex flex-wrap items-center gap-3 text-sm">{error}
          <Button size="sm" variant="outline" onClick={() => setReload(value => value + 1)}>Retry</Button></div>
      </Alert>}
      {notice && <Alert variant="success" role="status" className="mt-4"><CircleCheck aria-hidden="true" /><p className="text-sm">{notice}</p></Alert>}
      {activationBlocked && checks && <Alert variant="warning" className="mt-4"><CircleAlert aria-hidden="true" />
        <p className="text-sm">Activation is unavailable until every failed pre-activation check passes.</p></Alert>}

      {item?.status === 'disabled' && <Alert variant="warning" className="mt-4"><CircleAlert aria-hidden="true" />
        <p className="text-sm">Rejected institutions cannot be activated, and their staged data stays unpublished:
          not in scheduled sync and not in analytics. Retry onboarding to return it to Pending first.</p></Alert>}
      {!item && !error && <LoadingState label="Loading institution" />}

      {item && <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
        <div className="flex min-w-0 flex-col gap-4">
          {item.status === 'pending' && <SectionCard aria-labelledby="prepare-review">
            <SectionHeader id="prepare-review" title="Prepare for review"
              description="Fetching from Plaid stays a manual runbook step; this page never calls Plaid." />
            <ol className="flex flex-col divide-y border-t">
              <ReviewStep done={enabledAccounts > 0} title="Discover accounts"
                detail={`${enabledAccounts} of ${item.accounts.length} accounts in consumer scope`} />
              <ReviewStep done={item.has_cursor} title="Initial transaction sync"
                detail={item.has_cursor ? `${item.raw_transaction_count} transactions received` : 'Not synced yet'} />
              <ReviewStep done={item.has_cursor && item.normalized_transaction_count > 0} title="Normalize"
                detail={`${item.normalized_transaction_count} normalized transactions`} />
              <ReviewStep done={checksAllowActivation(checks)} title="Review checks and impact"
                detail="Activation previews the whole ledger and always asks for confirmation." />
            </ol>
          </SectionCard>}

          <SectionCard aria-labelledby="transactions-preview">
            <SectionHeader id="transactions-preview" title="Transactions"
              description={item.published ? `${total} transactions in this institution's consumer accounts`
                : `${total} transactions · unpublished, so no published classification yet`} />
            <div className="border-t px-1.5 pb-2 sm:px-2.5">
              {transactions.length === 0 && <p className="px-2.5 py-6 text-sm text-muted-foreground">No transactions yet.</p>}
              {groupByDay(transactions, row => row.transaction_date).map(({ date, rows }) => <DayGroup key={date} date={date}>
                {rows.map(row => <TransactionRow key={row.transaction_id} select={null}
                  title={<h3 className="break-words font-medium">{row.merchant_name || row.description || 'Unknown transaction'}</h3>}
                  meta={<>{row.account_name}{row.plaid_category && ` · ${row.plaid_category.replace(/_/g, ' ').toLowerCase()}`}</>}
                  pill={<TransactionTypeBadge type={row.transaction_type} />}
                  amount={<Amount value={row.amount}>{money(row.amount)}</Amount>} />)}
              </DayGroup>)}
              {total > pageSize && <Pagination className="px-2.5 pt-3" offset={offset} pageSize={pageSize}
                total={total} onPage={setOffset} />}
            </div>
          </SectionCard>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          {(item.status === 'pending' || item.status === 'deactivated') && <SectionCard aria-labelledby="activation-checks">
            <SectionHeader id="activation-checks" title="Pre-activation checks"
              description="Failed checks block activation; warnings are shown for review." />
            <div className="border-t">
              {checks ? <ActivationChecks checks={checks} /> : <LoadingState label="Loading checks" rows={1} />}
            </div>
          </SectionCard>}

          <SectionCard aria-labelledby="accounts">
            <SectionHeader id="accounts" title="Accounts" />
            <ul className="flex flex-col divide-y border-t">
              {item.accounts.map(account => <li key={account.account_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 sm:px-5">
                <AccountBadge institutionName={item.institution_name} accountName={account.name} accountMask={account.mask}
                  accountType={account.type} />
                <span className="text-[13px] text-muted-foreground">
                  {account.consumer_transactions_enabled ? `${account.transaction_count} transactions` : 'Outside consumer scope'}
                </span>
              </li>)}
              {item.accounts.length === 0 && <li className="px-4 py-3 text-sm text-muted-foreground sm:px-5">No accounts discovered.</li>}
            </ul>
          </SectionCard>
        </div>
      </div>}

      {item && dialog && <LifecycleDialog itemId={item.item_id} institutionName={item.institution_name} kind={dialog}
        open={dialog !== null} onOpenChange={open => { if (!open) setDialog(null) }} onDone={() => done(dialog)} />}
      {item && onboarding && <OnboardingDialog itemId={item.item_id} institutionName={item.institution_name} kind={onboarding}
        open={onboarding !== null} onOpenChange={open => { if (!open) setOnboarding(null) }}
        onDone={() => onboardingDone(onboarding)} />}
    </main>
  </div>
}
