type AccountBadgeProps = {
  institutionName: string
  accountName: string
  accountMask: string | null
  accountType: string
  accountSubtype?: string | null
}

type BadgeStyle = {
  label: string
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
    return { label: 'AMEX GOLD · 3008', className: 'border-amber-400 bg-amber-100 text-amber-950' }
  }
  if (institution.includes('AMERICAN EXPRESS') && account.includes('PLATINUM') && accountMask === '1004') {
    return { label: 'AMEX PLATINUM · 1004', className: 'border-slate-400 bg-slate-200 text-slate-900' }
  }
  if (institution.includes('CAPITAL ONE') && account.includes('VENTURE X') && accountMask === '5082') {
    return { label: 'VENTURE X · 5082', className: 'border-blue-950 bg-slate-900 text-white' }
  }
  if (institution.includes('CHASE') && isCredit && accountMask === '6987') {
    return { label: 'CHASE CARD · 6987', className: 'border-blue-700 bg-blue-600 text-white' }
  }
  if (institution.includes('CHASE') && account.includes('CHECKING') && accountMask === '1106') {
    return { label: 'CHASE CHECKING · 1106', className: 'border-red-700 bg-red-100 text-red-950' }
  }
  if (institution.includes('CHASE') && account.includes('SAVINGS') && accountMask === '3761') {
    return { label: 'CHASE SAVINGS · 3761', className: 'border-orange-600 bg-orange-100 text-orange-950' }
  }
  if (institution.includes('BANK OF AMERICA') && !isCredit && accountMask === '5041') {
    return { label: 'BOA CHECKING · 5041', className: 'border-red-700 bg-red-600 text-white' }
  }
  if (institution.includes('CAPITAL ONE') && !isCredit && accountMask === '9121') {
    return { label: 'CAPITAL ONE SAVINGS · 9121', className: 'border-orange-700 bg-orange-600 text-white' }
  }
  if (isCredit) {
    return { label: `CREDIT CARD · ${mask}`, className: 'border-indigo-300 bg-indigo-50 text-indigo-950' }
  }
  if (account.includes('SAVINGS') || subtype === 'SAVINGS') {
    return { label: `SAVINGS · ${mask}`, className: 'border-orange-500 bg-orange-100 text-orange-950' }
  }
  if (account.includes('CHECKING') || subtype === 'CHECKING' || type === 'DEPOSITORY') {
    return { label: `CHECKING · ${mask}`, className: 'border-red-500 bg-red-100 text-red-950' }
  }
  return { label: `${accountName || accountType} · ${mask}`, className: 'border-slate-300 bg-slate-100 text-slate-900' }
}

export default function AccountBadge(props: AccountBadgeProps) {
  const style = badgeStyle(props)
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-bold tracking-wide ${style.className}`}
      title={`${props.institutionName} — ${props.accountName}`}
    >
      {style.label}
    </span>
  )
}
