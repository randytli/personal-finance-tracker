import type React from 'react'
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Banknote,
  ChevronDown,
  CircleHelp,
  Hammer,
  HandCoins,
  HeartPulse,
  House,
  Landmark,
  MonitorPlay,
  Plane,
  Pencil,
  ReceiptText,
  ShoppingBag,
  ShoppingBasket,
  Ticket,
  TrainFront,
  UserRound,
  Utensils,
  Wrench,
  type LucideIcon,
} from 'lucide-react'

// Each category keeps one hue everywhere it appears (pills, list tiles, the category donut).
export type CategoryMetadata = { label: string; icon: LucideIcon; hue: number; saturation?: number }

const CATEGORY_METADATA: Record<string, CategoryMetadata> = {
  BANK_FEES: { label: 'Bank Fees', icon: ReceiptText, hue: 12 },
  ENTERTAINMENT: { label: 'Entertainment', icon: Ticket, hue: 335 },
  DINING: { label: 'Dining', icon: Utensils, hue: 24 },
  GENERAL_MERCHANDISE: { label: 'General Merchandise', icon: ShoppingBag, hue: 292 },
  GENERAL_SERVICES: { label: 'General Services', icon: Wrench, hue: 192 },
  GOVERNMENT_AND_NON_PROFIT: { label: 'Government & Nonprofit', icon: Landmark, hue: 212 },
  GROCERIES: { label: 'Groceries', icon: ShoppingBasket, hue: 92 },
  HOME_IMPROVEMENT: { label: 'Home Improvement', icon: Hammer, hue: 38 },
  INCOME: { label: 'Income', icon: Banknote, hue: 150 },
  LOAN_PAYMENTS: { label: 'Loan Payments', icon: HandCoins, hue: 258 },
  MEDICAL: { label: 'Medical', icon: HeartPulse, hue: 356 },
  PERSONAL_CARE: { label: 'Personal Care', icon: UserRound, hue: 312 },
  RENT_AND_UTILITIES: { label: 'Rent & Utilities', icon: House, hue: 48 },
  TRANSFER_IN: { label: 'Transfer In', icon: ArrowDownToLine, hue: 172 },
  TRANSFER_OUT: { label: 'Transfer Out', icon: ArrowUpFromLine, hue: 182 },
  TRANSPORTATION: { label: 'Transportation', icon: TrainFront, hue: 54 },
  TRAVEL: { label: 'Travel', icon: Plane, hue: 202 },
  UNCATEGORIZED: { label: 'Uncategorized', icon: CircleHelp, hue: 222, saturation: 15 },
}

const BENEFIT_CATEGORY_METADATA: Record<string, CategoryMetadata> = {
  DINING_CREDIT: { label: 'Dining', icon: Utensils, hue: 24 },
  TRAVEL_CREDIT: { label: 'Travel', icon: Plane, hue: 202 },
  SHOPPING_CREDIT: { label: 'Shopping', icon: ShoppingBag, hue: 292 },
  TRANSPORTATION_CREDIT: { label: 'Transportation', icon: TrainFront, hue: 54 },
  DIGITAL_ENTERTAINMENT_CREDIT: { label: 'Digital Entertainment', icon: MonitorPlay, hue: 268 },
  ENTERTAINMENT_CREDIT: { label: 'Entertainment', icon: Ticket, hue: 335 },
  GENERAL_SERVICES_CREDIT: { label: 'General Services', icon: Wrench, hue: 192 },
  UNCATEGORIZED: { label: 'Uncategorized', icon: CircleHelp, hue: 222, saturation: 15 },
}

function readableCategory(value: string) {
  return value.replace(/_/g, ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase())
}

export function categoryMetadata(category: string | null | undefined): CategoryMetadata {
  const value = category || 'UNCATEGORIZED'
  return CATEGORY_METADATA[value] || {
    label: readableCategory(value),
    icon: CircleHelp,
    hue: 222,
    saturation: 15,
  }
}

export function benefitCategoryMetadata(category: string | null | undefined): CategoryMetadata {
  const value = category || 'UNCATEGORIZED'
  return BENEFIT_CATEGORY_METADATA[value] || {
    label: readableCategory(value.replace(/_CREDIT$/, '')),
    icon: CircleHelp,
    hue: 222,
    saturation: 15,
  }
}

// CSS variable consumed by the hue-tinted classes below: "<hue> <saturation>%".
export function categoryTone(metadata: CategoryMetadata) {
  return { '--cat': `${metadata.hue} ${metadata.saturation ?? 80}%` } as React.CSSProperties
}

// Solid hue for chart segments and bars.
export function categoryColor(metadata: CategoryMetadata) {
  return `hsl(${metadata.hue} ${metadata.saturation ?? 80}% 62%)`
}

// Icon tile + name, for category lists where the name reads as a row label rather than a tag.
export function CategoryLabel({ category }: { category: string | null | undefined }) {
  const metadata = categoryMetadata(category)
  const Icon = metadata.icon
  return <span className="inline-flex min-w-0 items-center gap-2.5" style={categoryTone(metadata)}>
    <span aria-hidden="true" className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--cat)_60%/0.16)] text-[hsl(var(--cat)_72%)]">
      <Icon className="size-3.5" />
    </span>
    <span className="min-w-0 truncate text-sm font-medium" title={metadata.label}>{metadata.label}</span>
  </span>
}

function CategoryBadgeView({
  metadata,
  manual = false,
  editable = false,
  busy = false,
  expanded,
  controls,
  onClick,
}: {
  metadata: CategoryMetadata
  manual?: boolean
  editable?: boolean
  busy?: boolean
  expanded?: boolean
  controls?: string
  onClick?: () => void
}) {
  const Icon = metadata.icon
  const contents = <>
    <Icon aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
    <span className="min-w-0 [overflow-wrap:anywhere]">{metadata.label}</span>
    {manual && <Pencil aria-hidden="true" className="h-3 w-3 shrink-0" />}
    {manual && <span className="sr-only">(manually selected)</span>}
    {editable && <ChevronDown aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />}
  </>
  // Uppercase, hue-tinted pill; a manual choice adds a pencil and a ring so it is not signalled by colour alone.
  const className = `inline-flex max-w-full items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold uppercase leading-4 tracking-[0.04em] bg-[hsl(var(--cat)_60%/0.14)] text-[hsl(var(--cat)_72%)] ${
    manual ? 'ring-1 ring-inset ring-[hsl(var(--cat)_72%/0.6)]' : ''
  } ${editable || onClick ? 'cursor-pointer transition-colors hover:bg-[hsl(var(--cat)_60%/0.24)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default disabled:opacity-50' : ''}`

  return editable || onClick
    ? <button type="button" className={className} style={categoryTone(metadata)} disabled={busy} onClick={onClick}
        aria-expanded={expanded} aria-controls={controls}
        aria-label={editable ? `Edit category, currently ${metadata.label}` : undefined}>{contents}</button>
    : <span className={className} style={categoryTone(metadata)} title={metadata.label}>{contents}</span>
}

export function CategoryBadge({
  category,
  ...props
}: { category: string | null | undefined } & Omit<Parameters<typeof CategoryBadgeView>[0], 'metadata'>) {
  return <CategoryBadgeView metadata={categoryMetadata(category)} {...props} />
}

export function BenefitCategoryBadge({ category, onClick }: {
  category: string | null | undefined
  onClick?: () => void
}) {
  return <CategoryBadgeView metadata={benefitCategoryMetadata(category)} onClick={onClick} />
}

export const MANUAL_CATEGORY_VALUES = Object.freeze([
  'BANK_FEES', 'ENTERTAINMENT', 'DINING', 'GENERAL_MERCHANDISE',
  'GENERAL_SERVICES', 'GOVERNMENT_AND_NON_PROFIT', 'GROCERIES', 'HOME_IMPROVEMENT',
  'MEDICAL', 'PERSONAL_CARE', 'RENT_AND_UTILITIES', 'TRANSPORTATION', 'TRAVEL',
  'UNCATEGORIZED',
])
