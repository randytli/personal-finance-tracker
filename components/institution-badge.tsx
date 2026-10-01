const INSTITUTION_STYLES: Record<string, { label: string; className: string }> = {
  CHASE: { label: 'CHASE', className: 'border-blue-700 bg-blue-600 text-white' },
  'BANK OF AMERICA': { label: 'BANK OF AMERICA', className: 'border-red-700 bg-red-600 text-white' },
  'AMERICAN EXPRESS': { label: 'AMERICAN EXPRESS', className: 'border-sky-300 bg-sky-100 text-slate-900' },
  'CAPITAL ONE': { label: 'CAPITAL ONE', className: 'border-indigo-950 bg-indigo-900 text-white' },
}

export default function InstitutionBadge({ institutionName }: { institutionName: string }) {
  const name = institutionName.trim().replace(/\s+/g, ' ')
  const style = INSTITUTION_STYLES[name.toUpperCase()] || {
    label: name || 'Unknown institution',
    className: 'border-slate-300 bg-slate-100 text-slate-900',
  }

  return (
    <span
      className={`inline-flex max-w-full items-center [overflow-wrap:anywhere] rounded-md border px-2 py-1 text-[11px] font-semibold leading-4 tracking-wide ${style.className}`}
      title={name || 'Unknown institution'}
    >
      {style.label}
    </span>
  )
}
