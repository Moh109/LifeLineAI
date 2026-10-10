import { memo, useMemo, useState } from 'react'
import WaterGauge from './WaterGauge'
import { SOURCE_TAGS, TRIAGE, WATER_WORDS, effectivePriority, labelFor, waitText } from './lib'

const TABS = [
  { id: 'open', name: 'Waiting', match: (c) => c.status === 'open' },
  { id: 'assigned', name: 'Team assigned', match: (c) => c.status === 'assigned' },
  { id: 'done', name: 'Resolved', match: (c) => c.status === 'rescued' || c.status === 'closed' },
]
const PAGE = 60

export default function Queue({ cases, now, onSelect }) {
  const [tab, setTab] = useState('open')
  const [shown, setShown] = useState(PAGE)
  const counts = useMemo(() => Object.fromEntries(TABS.map((t) => [t.id, cases.filter(t.match).length])), [cases])
  const list = cases.filter(TABS.find((t) => t.id === tab).match)

  return (
    <section className="queue" aria-label="Rescue queue">
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className="tab"
            onClick={() => { setTab(t.id); setShown(PAGE) }}>
            {t.name} <span className="count">{counts[t.id]}</span>
          </button>
        ))}
      </div>
      <ol className="cards">
        {list.slice(0, shown).map((c) => (
          <CaseCard key={c.id} c={c} now={now} onSelect={onSelect} />
        ))}
      </ol>
      {list.length === 0 && (
        <p className="empty">
          {tab === 'open'
            ? 'No one is waiting. Call the Lifeline number, or start a surge to see the queue fill.'
            : tab === 'assigned' ? 'Assign a team from a waiting case and it moves here.' : 'Rescued and closed cases from the last two hours show here.'}
        </p>
      )}
      {list.length > shown && (
        <button className="more" onClick={() => setShown((n) => n + PAGE)}>
          Show {Math.min(PAGE, list.length - shown)} more of {list.length - shown}
        </button>
      )}
    </section>
  )
}

const CaseCard = memo(function CaseCard({ c, now, onSelect }) {
  const priority = effectivePriority(c, now)
  const label = labelFor(priority)
  const triage = TRIAGE[label]
  const resolved = c.status === 'rescued' || c.status === 'closed'

  return (
    <li>
      <button className={`card status-${c.status}`} style={{ '--band': resolved ? 'var(--rescued)' : triage.color }}
        onClick={() => onSelect(c.id)}>
        <div className="card-top">
          {c.status === 'open' ? (
            <span className="score">
              <span className="score-num">{priority}</span>
              <span className="score-word">{triage.word}</span>
            </span>
          ) : (
            <span className="score">
              <span className="score-word">{c.status === 'assigned' ? c.unit : c.status === 'rescued' ? 'Rescued' : 'Closed'}</span>
            </span>
          )}
          <span className="card-meta">
            {c.case_number}, {c.status === 'open' ? `waiting ${waitText(c.created_at, now)}` : `ETA ${c.eta_minutes ?? '?'} min`}
          </span>
        </div>
        <div className="card-body">
          <div className="card-text">
            {c.life_threatening && c.status === 'open' && <p className="life">Life-threatening{c.critical_reason ? `: ${c.critical_reason}` : ''}</p>}
            <p className="where">
              {c.address || c.landmark || 'Location not given yet'}
              {c.neighborhood && c.neighborhood !== 'Houston area' && <span className="hood"> {c.neighborhood}</span>}
            </p>
            {c.enriched && c.summary_en
              ? <p className="summary">{c.summary_en}</p>
              : <p className="summary">{WATER_WORDS[c.water_level || 'unknown']}{c.water_rising ? ', rising' : ''}</p>}
            <ul className="chips">
              {c.people_count ? <li>{c.people_count} {c.people_count === 1 ? 'person' : 'people'}</li> : null}
              {(c.vulnerable || []).map((v) => <li key={v}>{v}</li>)}
              {(c.medical_needs || []).map((m) => <li key={m} className="chip-med">{m}</li>)}
              {c.language && c.language !== 'English' && <li className="chip-lang">{c.language}</li>}
              {c.call_count > 1 && <li>called {c.call_count}x</li>}
              {c.location_confidence === 'approximate' && <li className="chip-warn">approx. pin</li>}
              {c.location_confidence === 'none' && (c.address || c.landmark) && <li className="chip-warn">not on map</li>}
              {SOURCE_TAGS[c.source] && <li className="chip-source">{SOURCE_TAGS[c.source]}</li>}
            </ul>
            {c.status === 'assigned' && c.callback_status && <p className="callback">Callback: {c.callback_status}</p>}
          </div>
          <WaterGauge level={c.water_level || 'unknown'} rising={c.water_rising} />
        </div>
      </button>
    </li>
  )
})
