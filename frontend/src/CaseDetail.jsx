import { useEffect, useState } from 'react'
import WaterGauge from './WaterGauge'
import { SOURCE_TAGS, TRIAGE, UNITS, WATER_WORDS, api, clockTime, effectivePriority, labelFor, waitText } from './lib'

// Callback is ticked by default for Immediate and Urgent cases; for Delayed (yellow) the dispatcher opts in.
const callBackByDefault = (c) => c.can_call_back && labelFor(effectivePriority(c)) !== 'yellow'

export default function CaseDetail({ c, now, onClose, onChanged, draft, setDraft, notify }) {
  const [unit, setUnit] = useState(c.unit || UNITS[0])
  const [eta, setEta] = useState(c.eta_minutes ?? 20)
  const [callBack, setCallBack] = useState(callBackByDefault(c))
  const [busy, setBusy] = useState(false)
  const [english, setEnglish] = useState(Boolean(c.transcript_en?.length))
  const [memory, setMemory] = useState([])

  useEffect(() => {
    setUnit(c.unit || UNITS[0])
    setEta(c.eta_minutes ?? 20)
    setCallBack(callBackByDefault(c))
    setEnglish(Boolean(c.transcript_en?.length))
    api(`/api/cases/${c.id}`).then((d) => setMemory(d.memory || [])).catch(() => setMemory([]))
  }, [c.id])

  const priority = effectivePriority(c, now)
  const triage = TRIAGE[labelFor(priority)]
  const resolved = c.status === 'rescued' || c.status === 'closed'

  async function run(action, success) {
    setBusy(true)
    try {
      const updated = await action()
      onChanged(updated)
      if (success) notify(success)
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const assign = (e) => {
    e.preventDefault()
    run(
      () => api(`/api/cases/${c.id}/assign`, { method: 'POST', body: { unit, eta_minutes: Number(eta) || null, call_back: callBack } }),
      callBack ? `${unit} assigned. Calling ${c.caller_name || 'the caller'} back now.` : `${unit} assigned.`,
    )
  }
  const setStatus = (status, msg) => run(() => api(`/api/cases/${c.id}/status`, { method: 'POST', body: { status } }), msg)
  const saveLocation = () =>
    run(async () => {
      const updated = await api(`/api/cases/${c.id}/location`, { method: 'POST', body: { lat: draft[0], lng: draft[1] } })
      setDraft(null)
      return updated
    }, 'Location saved.')

  const transcript = english && c.transcript_en?.length ? c.transcript_en : c.transcript || []

  return (
    <section className="detail" aria-label={`Case ${c.case_number}`}>
      <header className="detail-head" style={{ '--band': resolved ? 'var(--rescued)' : triage.color }}>
        <button className="back" onClick={onClose} aria-label="Back to queue">Back to queue</button>
        <div className="detail-title">
          <h2>{c.case_number}</h2>
          {c.status === 'open'
            ? <span className="pill" style={{ borderColor: triage.color }}>{priority} {triage.word}</span>
            : <span className="pill pill-quiet">{c.status === 'assigned' ? `${c.unit} assigned` : c.status === 'rescued' ? 'Rescued' : 'Closed'}</span>}
        </div>
        <p className="detail-sub">
          Received {clockTime(c.created_at)}, {c.status === 'open' ? `waiting ${waitText(c.created_at, now)}` : `updated ${waitText(c.updated_at, now)} ago`}
          {SOURCE_TAGS[c.source] ? `. ${SOURCE_TAGS[c.source]}` : ''}
        </p>
      </header>

      <div className="detail-scroll">
        {c.needs_review && <p className="review-badge">Needs review: {c.review_reason || 'check this case'}</p>}
        {c.life_threatening && <p className="life life-big">Life-threatening{c.critical_reason ? `: ${c.critical_reason}` : ''}</p>}

        <div className="detail-where">
          <WaterGauge level={c.water_level || 'unknown'} rising={c.water_rising} size={64} />
          <div>
            <p className="where big">{c.address || c.landmark || 'Location not given yet'}</p>
            {c.landmark && c.address && <p className="muted">{/^near\b/i.test(c.landmark) ? c.landmark : `Near ${c.landmark}`}</p>}
            <p className="muted">
              {WATER_WORDS[c.water_level || 'unknown']}{c.water_rising ? ', rising' : ''}
              {c.neighborhood ? `. ${c.neighborhood}` : ''}
            </p>
          </div>
        </div>

        <p className="summary-big">{c.summary_en}</p>

        {!resolved && (
          <form className="dispatch" onSubmit={assign}>
            <h3>Send a team</h3>
            <div className="dispatch-row">
              <label>
                Team
                <input list="units" value={unit} onChange={(e) => setUnit(e.target.value)} required maxLength={80} />
                <datalist id="units">{UNITS.map((u) => <option key={u} value={u} />)}</datalist>
              </label>
              <label className="eta">
                Arrives in (min)
                <input type="number" min="0" max="600" value={eta} onChange={(e) => setEta(e.target.value)} />
              </label>
            </div>
            {/* Hidden when callbacks aren't set up (no CALLBACK_AGENT_ID) or the case has no real phone */}
            {c.can_call_back && (
              <label className="check">
                <input type="checkbox" checked={callBack} onChange={(e) => setCallBack(e.target.checked)} />
                {`Call ${c.phone} back with the arrival time${labelFor(priority) === 'yellow' ? ' (optional for Delayed cases)' : ''}`}
              </label>
            )}            <div className="actions">
              <button type="submit" className="primary" disabled={busy}>
                {c.status === 'assigned' ? 'Reassign' : callBack && c.can_call_back ? 'Assign and call back' : 'Assign team'}
              </button>
              {c.status === 'assigned' && <button type="button" onClick={() => setStatus('rescued', 'Marked rescued.')} disabled={busy}>Mark rescued</button>}
              {c.status === 'assigned' && c.can_call_back && (
                <button type="button" disabled={busy}
                  onClick={() => run(() => api(`/api/cases/${c.id}/callback`, { method: 'POST' }), 'Calling back again.')}>
                  Call back again
                </button>
              )}
            </div>
            {c.callback_status && <p className="callback">Callback: {c.callback_status}</p>}
          </form>
        )}

        <div className="actions secondary">
          {!resolved && <button type="button" onClick={() => setStatus('closed', 'Case closed.')} disabled={busy}>Close as duplicate or false</button>}
          {resolved && <button type="button" onClick={() => setStatus('open', 'Case reopened.')} disabled={busy}>Reopen</button>}
          {c.status === 'open' && <button type="button" onClick={() => setStatus('rescued', 'Marked rescued.')} disabled={busy}>Mark rescued</button>}
        </div>

        {c.location_confidence !== 'high' && !resolved && (
          <div className="locate">
            <h3>Fix the pin</h3>
            {draft ? (
              <>
                <p className="muted">Drag the blue pin on the map to where they are, then save.</p>
                <div className="actions">
                  <button className="primary" onClick={saveLocation} disabled={busy}>Save location</button>
                  <button onClick={() => setDraft(null)}>Cancel</button>
                </div>
              </>
            ) : (
              <>
                <p className="muted">
                  {c.location_confidence === 'approximate'
                    ? 'The street address did not match the map, so this pin marks the neighborhood only.'
                    : 'This address is not on the map yet.'}
                </p>
                <button onClick={() => setDraft(c.lat != null ? [c.lat, c.lng] : [29.76, -95.37])}>Place pin by hand</button>
              </>
            )}
          </div>
        )}

        <h3>Why this priority</h3>
        <ul className="reasons">
          {(c.reasons || []).map((r) => <li key={r}>{r}</li>)}
          {c.status === 'open' && c.wait_bonus > 0 && <li>Waiting time (+{Math.floor(priority - c.base_priority)})</li>}
        </ul>

        <h3>Caller</h3>
        <dl className="facts">
          <Fact k="Name" v={c.caller_name} />
          <Fact k="Phone" v={c.phone} />
          <Fact k="Language" v={c.language} />
          <Fact k="People" v={c.people_count} />
          <Fact k="With them" v={(c.vulnerable || []).join(', ')} />
          <Fact k="Medical" v={(c.medical_needs || []).join(', ')} />
          <Fact k="Injuries" v={c.injuries} />
          <Fact k="Pets" v={c.pets} />
          <Fact k="Phone battery" v={c.battery_pct != null ? `${c.battery_pct}%` : null} />
          <Fact k="Calls" v={c.call_count > 1 ? `${c.call_count} calls` : null} />
          <Fact k="Notes" v={c.notes} />
        </dl>

        {memory.length > 0 && (
          <>
            <h3>Earlier from this number</h3>
            <ul className="memory">{memory.map((m, i) => <li key={i}>{m}</li>)}</ul>
          </>
        )}

        {transcript.length > 0 && (
          <>
            <div className="transcript-head">
              <h3>{c.source === 'social' ? 'Original post' : 'Transcript'}</h3>
              {c.transcript_en?.length > 0 && (
                <button className="link" onClick={() => setEnglish((v) => !v)}>
                  {english ? `Show original (${c.language})` : 'Show English'}
                </button>
              )}
            </div>
            <ol className="transcript">
              {transcript.map((line, i) => (
                <li key={i} className={line.role === 'user' || line.role === 'caller' ? 'from-caller' : 'from-agent'}>
                  <span className="who">
                    {line.role === 'user' || line.role === 'caller' ? 'Caller' : 'Lifeline'}
                    {line.call === 'callback' ? ' (callback)' : ''}
                  </span>
                  {line.message}
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </section>
  )
}

function Fact({ k, v }) {
  if (v === null || v === undefined || v === '') return null
  return (
    <>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </>
  )
}
