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

export type CategoryMetadata = { label: string; icon: LucideIcon }

const CATEGORY_METADATA: Record<string, CategoryMetadata> = {
  BANK_FEES: { label: 'Bank Fees', icon: ReceiptText },
  ENTERTAINMENT: { label: 'Entertainment', icon: Ticket },
  FOOD_AND_DRINK: { label: 'Food & Drink', icon: Utensils },
  GENERAL_MERCHANDISE: { label: 'General Merchandise', icon: ShoppingBag },
  GENERAL_SERVICES: { label: 'General Services', icon: Wrench },
  GOVERNMENT_AND_NON_PROFIT: { label: 'Government & Nonprofit', icon: Landmark },
  GROCERIES: { label: 'Groceries', icon: ShoppingBasket },
  HOME_IMPROVEMENT: { label: 'Home Improvement', icon: Hammer },
  INCOME: { label: 'Income', icon: Banknote },
  LOAN_PAYMENTS: { label: 'Loan Payments', icon: HandCoins },
  MEDICAL: { label: 'Medical', icon: HeartPulse },
  PERSONAL_CARE: { label: 'Personal Care', icon: UserRound },
  RENT_AND_UTILITIES: { label: 'Rent & Utilities', icon: House },
  TRANSFER_IN: { label: 'Transfer In', icon: ArrowDownToLine },
  TRANSFER_OUT: { label: 'Transfer Out', icon: ArrowUpFromLine },
  TRANSPORTATION: { label: 'Transportation', icon: TrainFront },
  TRAVEL: { label: 'Travel', icon: Plane },
  UNCATEGORIZED: { label: 'Uncategorized', icon: CircleHelp },
}

export function categoryMetadata(category: string | null | undefined): CategoryMetadata {
  const value = category || 'UNCATEGORIZED'
  return CATEGORY_METADATA[value] || {
    label: value.replace(/_/g, ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase()),
    icon: CircleHelp,
  }
}

export function CategoryBadge({
  category,
  manual = false,
  editable = false,
  busy = false,
  expanded,
  controls,
  onClick,
}: {
  category: string | null | undefined
  manual?: boolean
  editable?: boolean
  busy?: boolean
  expanded?: boolean
  controls?: string
  onClick?: () => void
}) {
  const metadata = categoryMetadata(category)
  const Icon = metadata.icon
  const contents = <>
    <Icon aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
    <span>{metadata.label}</span>
    {manual && <Pencil aria-hidden="true" className="h-3 w-3 shrink-0" />}
    {manual && <span className="sr-only">(manually selected)</span>}
    {editable && <ChevronDown aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />}
  </>
  const className = `inline-flex max-w-full items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium ${
    manual ? 'border-blue-300 bg-blue-50 text-blue-900' : 'border-slate-300 bg-slate-50 text-slate-800'
  } ${editable ? 'cursor-pointer hover:border-blue-400 hover:bg-blue-50 disabled:cursor-default disabled:opacity-50' : ''}`

  return editable
    ? <button type="button" className={className} disabled={busy} onClick={onClick}
        aria-expanded={expanded} aria-controls={controls}
        aria-label={`Edit category, currently ${metadata.label}`}>{contents}</button>
    : <span className={className} title={metadata.label}>{contents}</span>
}

export const MANUAL_CATEGORY_VALUES = Object.freeze([
  'BANK_FEES', 'ENTERTAINMENT', 'FOOD_AND_DRINK', 'GENERAL_MERCHANDISE',
  'GENERAL_SERVICES', 'GOVERNMENT_AND_NON_PROFIT', 'GROCERIES', 'HOME_IMPROVEMENT',
  'MEDICAL', 'PERSONAL_CARE', 'RENT_AND_UTILITIES', 'TRANSPORTATION', 'TRAVEL',
  'UNCATEGORIZED',
])
