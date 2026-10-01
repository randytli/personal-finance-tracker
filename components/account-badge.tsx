type AccountBadgeProps = {
  institutionName: string
  accountName: string
  accountMask: string | null
  accountType: string
  accountSubtype?: string | null
}

type BadgeStyle = {
  label: string
  /** Swatch colour that identifies the account at a glance. */
  className: string
}

function normalized(value: string | null | undefined) {
  return (value || '').toUpperCase().replace(/[^A-Z0-9]+/g, ' ').trim()
}

function badgeStyle({
  institutionName,
  accountName,
  accountMask,
  accountType,
  accountSubtype,
}: AccountBadgeProps): BadgeStyle {
  const institution = normalized(institutionName)
  const account = normalized(accountName)
  const type = normalized(accountType)
  const subtype = normalized(accountSubtype)
  const mask = accountMask || '••••'
  const isCredit = type === 'CREDIT' || subtype.includes('CREDIT CARD')

  if (institution.includes('AMERICAN EXPRESS') && account.includes('GOLD') && accountMask === '3008') {
    return { label: 'AMEX GOLD · 3008', className: 'bg-amber-400' }
  }
  if (institution.includes('AMERICAN EXPRESS') && account.includes('PLATINUM') && accountMask === '1004') {
    return { label: 'AMEX PLATINUM · 1004', className: 'bg-slate-400' }
  }
  if (institution.includes('CAPITAL ONE') && account.includes('VENTURE X') && accountMask === '5082') {
    return { label: 'VENTURE X · 5082', className: 'bg-slate-900' }
  }
  if (institution.includes('CHASE') && isCredit && accountMask === '6987') {
    return { label: 'CHASE CARD · 6987', className: 'bg-blue-600' }
  }
  if (institution.includes('CHASE') && account.includes('CHECKING') && accountMask === '1106') {
    return { label: 'CHASE CHECKING · 1106', className: 'bg-red-300 ring-1 ring-inset ring-red-700/60' }
  }
  if (institution.includes('CHASE') && account.includes('SAVINGS') && accountMask === '3761') {
    return { label: 'CHASE SAVINGS · 3761', className: 'bg-orange-200 ring-1 ring-inset ring-orange-600/60' }
  }
  if (institution.includes('BANK OF AMERICA') && !isCredit && accountMask === '5041') {
    return { label: 'BOA CHECKING · 5041', className: 'bg-red-600' }
  }
  if (institution.includes('CAPITAL ONE') && !isCredit && accountMask === '9121') {
    return { label: 'CAPITAL ONE SAVINGS · 9121', className: 'bg-orange-600' }
  }
  if (isCredit) {
    return { label: `CREDIT CARD · ${mask}`, className: 'bg-indigo-300' }
  }
  if (account.includes('SAVINGS') || subtype === 'SAVINGS') {
    return { label: `SAVINGS · ${mask}`, className: 'bg-orange-300' }
  }
  if (account.includes('CHECKING') || subtype === 'CHECKING' || type === 'DEPOSITORY') {
    return { label: `CHECKING · ${mask}`, className: 'bg-red-300' }
  }
  return { label: `${accountName || accountType} · ${mask}`, className: 'bg-slate-300' }
}

export default function AccountBadge(props: AccountBadgeProps) {
  const style = badgeStyle(props)
  return (
    <span
      className="inline-flex max-w-full items-center gap-1.5 [overflow-wrap:anywhere] rounded-md border bg-card px-2 py-1 text-[11px] font-semibold leading-4 tracking-wide text-foreground"
      title={`${props.institutionName} — ${props.accountName}`}
    >
      <span aria-hidden="true" className={`h-2 w-3 shrink-0 rounded-[2px] ${style.className}`} />
      {style.label}
    </span>
  )
}
