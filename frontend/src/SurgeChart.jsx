import { useEffect, useMemo, useRef, useState } from 'react'

// Calls per 15 seconds over the last 10 minutes, like a river-gauge hydrograph.
// The dashed line is roughly what the human operators on shift can answer.
// Every call above it would have heard hold music without Lifeline.
const BUCKET_MS = 15000
const WINDOW_BUCKETS = 40
export const OPERATOR_CAPACITY_PER_MIN = 12
const CAPACITY = OPERATOR_CAPACITY_PER_MIN / 4

export default function SurgeChart({ series }) {
  const wrap = useRef(null)
  const [width, setWidth] = useState(320)
  const [hover, setHover] = useState(null)

  useEffect(() => {
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(200, entry.contentRect.width)))
    if (wrap.current) ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])

  const buckets = useMemo(() => {
    const counts = new Map((series || []).map((s) => [Math.floor(new Date(s.bucket).getTime() / BUCKET_MS), s.calls]))
    const nowBucket = Math.floor(Date.now() / BUCKET_MS)
    return Array.from({ length: WINDOW_BUCKETS }, (_, i) => {
      const b = nowBucket - WINDOW_BUCKETS + 1 + i
      return { t: b * BUCKET_MS, calls: counts.get(b) || 0 }
    })
  }, [series])

  const height = 64
  const top = 6
  const base = height - 2
  const maxCalls = Math.max(CAPACITY * 2.5, ...buckets.map((b) => b.calls))
  const y = (v) => base - (v / maxCalls) * (base - top)
  const slot = width / WINDOW_BUCKETS
  const barW = Math.max(2, slot - 2)
  const capY = y(CAPACITY)
  const overflow = buckets.reduce((sum, b) => sum + Math.max(0, b.calls - CAPACITY), 0)

  return (
    <div className="surge-chart" ref={wrap}>
      <svg width={width} height={height} role="img"
        aria-label={`Calls every 15 seconds over the last 10 minutes. Peak ${Math.max(...buckets.map((b) => b.calls))}.`}
        onMouseLeave={() => setHover(null)}>
        <line x1="0" x2={width} y1={base} y2={base} stroke="var(--line)" />
        {buckets.map((b, i) => {
          const h = base - y(b.calls)
          return (
            <g key={b.t} onMouseEnter={() => setHover(i)}>
              <rect x={i * slot} y={top} width={slot} height={base - top} fill="transparent" />
              {b.calls > 0 && (
                <path
                  d={roundedTop(i * slot + 1, y(b.calls), barW, h, Math.min(3, barW / 2))}
                  fill="var(--water)"
                  opacity={hover === null || hover === i ? 1 : 0.55}
                />
              )}
            </g>
          )
        })}
        <line x1="0" x2={width} y1={capY} y2={capY} stroke="var(--ink)" strokeDasharray="4 3" strokeWidth="1" />
        <text x="2" y={capY - 4} fontSize="11" fill="var(--muted)">Operators on shift</text>
      </svg>
      {hover !== null && (
        <div className="chart-tip" style={{ left: Math.min(width - 120, Math.max(0, hover * slot - 40)) }}>
          <strong>{buckets[hover].calls} calls</strong>{' '}
          {new Date(buckets[hover].t).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })}
        </div>
      )}
      <p className="chart-note">
        {overflow > 0
          ? `${overflow} calls above operator capacity in the last 10 minutes. Lifeline answered every one.`
          : 'Calls every 15 seconds, last 10 minutes'}
      </p>
    </div>
  )
}

function roundedTop(x, y0, w, h, r) {
  if (h <= r) return `M${x} ${y0 + h} V${y0} H${x + w} V${y0 + h} Z`
  return `M${x} ${y0 + h} V${y0 + r} Q${x} ${y0} ${x + r} ${y0} H${x + w - r} Q${x + w} ${y0} ${x + w} ${y0 + r} V${y0 + h} Z`
}
