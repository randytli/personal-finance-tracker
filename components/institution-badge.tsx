import { BrandSwatch, type Swatch } from '@/components/account-badge'

// Two-tone swatches from each bank's own colours, so the two blue brands (Chase, Amex) still differ.
const INSTITUTION_STYLES: Record<string, { label: string; swatch: Swatch }> = {
  CHASE: { label: 'CHASE', swatch: { shape: 'institution', background: '#117ACA' } },
  'BANK OF AMERICA': { label: 'BANK OF AMERICA', swatch: { shape: 'institution', background: 'linear-gradient(180deg, #E31837 50%, #1B3A8C 50%)' } },
  'AMERICAN EXPRESS': { label: 'AMERICAN EXPRESS', swatch: { shape: 'institution', background: '#006FCF', inset: '#FFFFFF' } },
  'CAPITAL ONE': { label: 'CAPITAL ONE', swatch: { shape: 'institution', background: 'linear-gradient(160deg, #0B4F80 58%, #D9372A 58%)' } },
}

export function institutionBadgeStyle(name: string): { label: string; swatch: Swatch } {
  return INSTITUTION_STYLES[name.toUpperCase()] || {
    label: name || 'Unknown institution',
    swatch: { shape: 'institution', background: '#5B6584' },
  }
}

export default function InstitutionBadge({ institutionName }: { institutionName: string }) {
  const name = institutionName.trim().replace(/\s+/g, ' ')
  const style = institutionBadgeStyle(name)

  return (
    <span
      className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-[11px] font-bold leading-4 tracking-[0.04em] text-foreground"
      title={name || 'Unknown institution'}
    >
      <BrandSwatch swatch={style.swatch} />
      <span className="truncate">{style.label}</span>
    </span>
  )
}
