const INSTITUTION_STYLES: Record<string, { label: string; className: string }> = {
  CHASE: { label: 'CHASE', className: 'bg-blue-600' },
  'BANK OF AMERICA': { label: 'BANK OF AMERICA', className: 'bg-red-600' },
  'AMERICAN EXPRESS': { label: 'AMERICAN EXPRESS', className: 'bg-sky-300' },
  'CAPITAL ONE': { label: 'CAPITAL ONE', className: 'bg-indigo-900' },
}

export default function InstitutionBadge({ institutionName }: { institutionName: string }) {
  const name = institutionName.trim().replace(/\s+/g, ' ')
  const style = INSTITUTION_STYLES[name.toUpperCase()] || {
    label: name || 'Unknown institution',
    className: 'bg-slate-300',
  }

  return (
    <span
      className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-[11px] font-bold leading-4 tracking-[0.04em] text-foreground"
      title={name || 'Unknown institution'}
    >
      <span aria-hidden="true" className={`h-2 w-3 shrink-0 rounded-[2px] ${style.className}`} />
      <span className="truncate">{style.label}</span>
    </span>
  )
}
