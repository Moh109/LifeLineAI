// A standing figure with floodwater drawn to the reported depth.
// Water level is the biggest driver of the triage score, so it gets its own glyph.

const LEVEL_HEIGHT = { none: 0, ankle: 0.08, knee: 0.27, waist: 0.48, chest: 0.68, roof: 1 }

export default function WaterGauge({ level, rising, size = 40 }) {
  const known = level in LEVEL_HEIGHT
  const h = 46
  const fill = known ? LEVEL_HEIGHT[level] : 0
  const waterTop = h - fill * (h - 4)
  const label = known
    ? `Water ${level === 'roof' ? 'over their head, on the roof' : `at ${level}`}${rising ? ', rising' : ''}`
    : 'Water depth unknown'

  return (
    <svg className="gauge" width={size * 0.7} height={size} viewBox="0 0 28 46" role="img" aria-label={label}>
      <title>{label}</title>
      {level === 'roof' && <path d="M3 9 L14 1 L25 9" fill="none" stroke="var(--ink)" strokeWidth="2" strokeLinejoin="round" />}
      <g fill={known ? 'var(--ink)' : 'none'} stroke={known ? 'none' : 'var(--muted)'} strokeDasharray={known ? undefined : '2 2'}>
        <circle cx="14" cy={level === 'roof' ? 13 : 7} r="4" />
        <rect x="9" y={level === 'roof' ? 18 : 12} width="10" height={level === 'roof' ? 15 : 17} rx="4" />
        {level !== 'roof' && <rect x="9.5" y="27" width="4" height="18" rx="2" />}
        {level !== 'roof' && <rect x="14.5" y="27" width="4" height="18" rx="2" />}
      </g>
      {fill > 0 && (
        <g>
          <rect x="0" y={waterTop} width="28" height={h - waterTop} fill="var(--water)" opacity="0.78" />
          <path d={`M0 ${waterTop} q3.5 -2 7 0 t7 0 t7 0 t7 0`} fill="none" stroke="var(--water)" strokeWidth="1.5" />
        </g>
      )}
      {rising && fill > 0 && fill < 1 && (
        <path d={`M24 ${waterTop - 4} l-3 -4 l-3 4`} fill="none" stroke="var(--water)" strokeWidth="2" strokeLinecap="round" />
      )}
      {!known && <text x="14" y="44" textAnchor="middle" fontSize="9" fill="var(--muted)">?</text>}
    </svg>
  )
}
