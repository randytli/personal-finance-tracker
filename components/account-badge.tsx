import type React from 'react'

export type AccountBadgeProps = {
  institutionName: string
  accountName: string
  accountMask: string | null
  accountType: string
  accountSubtype?: string | null
}

// Swatch colours follow the real card or bank. Credit cards are card-shaped in the card's own
// finish; bank accounts are round in the bank's colour, filled for checking and a ring for savings,
// so accounts at one bank still differ by shape.
export type Swatch =
  | { shape: 'card'; from: string; to: string }
  | { shape: 'checking'; color: string }
  | { shape: 'savings'; color: string; fill?: string }
  | { shape: 'institution'; background: string; inset?: string }

type BadgeStyle = { label: string; swatch: Swatch }

const card = (from: string, to: string): Swatch => ({ shape: 'card', from, to })

function normalized(value: string | null | undefined) {
  return (value || '').toUpperCase().replace(/[^A-Z0-9]+/g, ' ').trim()
}

export function accountBadgeStyle({
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
    return { label: 'AMEX GOLD · 3008', swatch: card('#EDD089', '#B48A36') }
  }
  if (institution.includes('AMERICAN EXPRESS') && account.includes('PLATINUM') && accountMask === '1004') {
    return { label: 'AMEX PLATINUM · 1004', swatch: card('#EEF1F4', '#A3AAB4') }
  }
  if (institution.includes('CAPITAL ONE') && account.includes('VENTURE X') && accountMask === '5082') {
    return { label: 'VENTURE X · 5082', swatch: card('#3B3F46', '#0E1013') }
  }
  if (institution.includes('CHASE') && isCredit && accountMask === '6987') {
    return { label: 'FREEDOM FLEX · 6987', swatch: card('#7CCBF2', '#2384CC') }
  }
  if (institution.includes('CHASE') && account.includes('CHECKING') && accountMask === '1106') {
    return { label: 'CHASE CHECKING · 1106', swatch: { shape: 'checking', color: '#117ACA' } }
  }
  if (institution.includes('CHASE') && account.includes('SAVINGS') && accountMask === '3761') {
    return { label: 'CHASE SAVINGS · 3761', swatch: { shape: 'savings', color: '#5DB4F0' } }
  }
  if (institution.includes('BANK OF AMERICA') && !isCredit && accountMask === '5041') {
    return { label: 'BOA CHECKING · 5041', swatch: { shape: 'checking', color: '#E31837' } }
  }
  if (institution.includes('CAPITAL ONE') && !isCredit && accountMask === '9121') {
    return { label: 'CAPITAL ONE SAVINGS · 9121', swatch: { shape: 'savings', color: '#D9372A', fill: '#0B4F80' } }
  }
  if (isCredit) {
    return { label: `CREDIT CARD · ${mask}`, swatch: card('#8C97B5', '#5B6584') }
  }
  if (account.includes('SAVINGS') || subtype === 'SAVINGS') {
    return { label: `SAVINGS · ${mask}`, swatch: { shape: 'savings', color: '#8C97B5' } }
  }
  if (account.includes('CHECKING') || subtype === 'CHECKING' || type === 'DEPOSITORY') {
    return { label: `CHECKING · ${mask}`, swatch: { shape: 'checking', color: '#8C97B5' } }
  }
  return { label: `${accountName || accountType} · ${mask}`, swatch: { shape: 'checking', color: '#5B6584' } }
}

// A hairline keeps dark swatches (Venture X, navy) visible on the dark surfaces.
const hairline = 'inset 0 0 0 1px rgb(255 255 255 / 0.22)'

export function BrandSwatch({ swatch }: { swatch: Swatch }) {
  let style: React.CSSProperties
  let className = 'shrink-0'
  if (swatch.shape === 'card') {
    className += ' h-[11px] w-4 rounded-[3px]'
    style = { background: `linear-gradient(135deg, ${swatch.from}, ${swatch.to})`, boxShadow: hairline }
  } else if (swatch.shape === 'checking') {
    className += ' size-2.5 rounded-full'
    style = { background: swatch.color, boxShadow: hairline }
  } else if (swatch.shape === 'savings') {
    className += ' size-2.5 rounded-full'
    style = { background: swatch.fill ?? 'transparent', boxShadow: `inset 0 0 0 2.5px ${swatch.color}` }
  } else {
    className += ' h-[11px] w-4 rounded-[3px]'
    style = { background: swatch.background, boxShadow: swatch.inset ? `inset 0 0 0 1.5px ${swatch.inset}` : hairline }
  }
  return <span aria-hidden="true" data-swatch={swatch.shape} className={className} style={style} />
}

export default function AccountBadge(props: AccountBadgeProps) {
  const style = accountBadgeStyle(props)
  return (
    <span
      className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-[11px] font-bold leading-4 tracking-[0.04em] text-foreground"
      title={`${props.institutionName} — ${props.accountName}`}
    >
      <BrandSwatch swatch={style.swatch} />
      <span className="truncate">{style.label}</span>
    </span>
  )
}
