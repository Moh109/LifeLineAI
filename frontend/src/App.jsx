import { useEffect, useMemo, useState } from 'react'
import CaseDetail from './CaseDetail'
import IntakeDialog from './IntakeDialog'
import MapView from './MapView'
import Queue from './Queue'
import SurgeChart from './SurgeChart'
import { api, sortCases } from './lib'
import { useLive } from './useLive'

export default function App() {
  const { cases, stats, features, connected, surge, alerts, dismissAlert, mergeCase } = useLive()
  const [selectedId, setSelectedId] = useState(null)
  const [draft, setDraft] = useState(null)
  const [now, setNow] = useState(Date.now())
  const [intakeOpen, setIntakeOpen] = useState(false)
  const [toast, setToast] = useState(null)

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 15000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 4500)
    return () => clearTimeout(t)
  }, [toast])

  const list = useMemo(() => sortCases([...cases.values()], now), [cases, now])
  const selected = selectedId ? cases.get(selectedId) : null
  const notify = (text, kind = 'ok') => setToast({ text, kind, key: Date.now() })

  const select = (id) => {
    setDraft(null)
    setSelectedId(id)
  }

  async function startSurge() {
    try {
      await api('/api/demo/surge', { method: 'POST', body: { count: 300, seconds: 60 } })
      notify('Surge started: 300 calls over the next minute.')
    } catch (err) {
      notify(err.message, 'error')
    }
  }

  async function clearSimulated() {
    try {
      const r = await api('/api/demo/reset', { method: 'POST' })
      if (selected?.source === 'simulated') setSelectedId(null)
      notify(`Removed ${r.removed} simulated cases.`)
    } catch (err) {
      notify(err.message, 'error')
    }
  }

  const simulatedCount = list.filter((c) => c.source === 'simulated').length

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>Lifeline</h1>
          <p>Overflow rescue line for Houston 911</p>
          <p className={`conn ${connected ? 'on' : 'off'}`} role="status">
            <span className="dot" aria-hidden="true" />{connected ? 'Live' : 'Reconnecting'}
          </p>
        </div>

        <div className="surge">
          <div className="surge-figure">
            <span className="big-num">{stats?.calls_last_minute ?? 0}</span>
            <span className="big-label">calls in the last minute</span>
          </div>
          <SurgeChart series={stats?.series} />
        </div>

        <dl className="tallies">
          <div><dt>Waiting</dt><dd>{stats?.open ?? 0}</dd></div>
          <div><dt>Team assigned</dt><dd>{stats?.assigned ?? 0}</dd></div>
          <div><dt>Rescued today</dt><dd>{stats?.rescued_24h ?? 0}</dd></div>
          <div><dt>Average wait</dt><dd>{stats ? `${Math.round(stats.avg_wait_min)} min` : '0 min'}</dd></div>
        </dl>

        <div className="top-actions">
          <button onClick={() => setIntakeOpen(true)} disabled={features && !features.gemini}
            title={features && !features.gemini ? 'Add GEMINI_API_KEY on the server to use this' : undefined}>
            Add from a post
          </button>
          <button className="surge-btn" onClick={startSurge} disabled={surge}>
            {surge ? 'Surge running' : 'Run Harvey surge'}
          </button>
          {simulatedCount > 0 && !surge && (
            <button className="quiet" onClick={clearSimulated}>Clear {simulatedCount} simulated</button>
          )}
        </div>
      </header>

      <main className="workspace">
        <div className="map-wrap">
          <MapView cases={list} selectedId={selectedId} onSelect={select} draft={draft} onDraftMove={setDraft} now={now} />
          <div className="alerts" aria-live="assertive">
            {alerts.map((a) => (
              <div key={a.key} className="alert">
                <p className="alert-title">Life-threatening, {a.case.case_number}</p>
                <p>{a.case.critical_reason || a.case.summary_en}</p>
                <p className="muted">{a.case.address || a.case.landmark || 'Location still being collected'}</p>
                <div className="actions">
                  <button className="primary" onClick={() => { select(a.case.id); dismissAlert(a.key) }}>Open case</button>
                  <button onClick={() => dismissAlert(a.key)}>Dismiss</button>
                </div>
              </div>
            ))}
          </div>
          <Legend />
        </div>

        <aside className="side">
          {selected ? (
            <CaseDetail key={selected.id} c={selected} now={now} onClose={() => select(null)} onChanged={mergeCase}
              draft={draft} setDraft={setDraft} notify={notify} />
          ) : (
            <Queue cases={list} now={now} onSelect={select} />
          )}
        </aside>
      </main>

      <IntakeDialog open={intakeOpen} onClose={() => setIntakeOpen(false)} notify={notify}
        onCreated={(c) => { mergeCase(c); select(c.id) }} />

      {toast && <div key={toast.key} className={`toast ${toast.kind}`} role="status">{toast.text}</div>}
    </div>
  )
}

function Legend() {
  return (
    <ul className="legend" aria-label="Map key">
      <li><span className="sw" style={{ background: 'var(--red)' }} />Immediate, 60+</li>
      <li><span className="sw" style={{ background: 'var(--orange)' }} />Urgent, 35 to 59</li>
      <li><span className="sw" style={{ background: 'var(--yellow)' }} />Delayed, under 35</li>
      <li><span className="sw ring" />Team assigned</li>
      <li><span className="sw" style={{ background: 'var(--rescued)' }} />Rescued</li>
    </ul>
  )
}
