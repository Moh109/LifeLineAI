// Demo mode: the whole backend, in this browser tab. Cases come from cases.json (made by
// scripts/build_static_demo.py with the real scoring rules); every dispatcher action only
// changes this in-memory copy, and a page reload starts over. No network calls.
import seed from './cases.json'

const WAIT_BONUS_EVERY_MIN = 10
const WAIT_BONUS_MAX = 20
const ago = (minutes, now) => (minutes == null ? null : new Date(now - minutes * 60000).toISOString())

function withWaitBonus(c, now = Date.now()) {
  const waited = (now - new Date(c.created_at).getTime()) / 60000
  const bonus = c.status === 'open' ? Math.min(WAIT_BONUS_MAX, Math.floor(waited / WAIT_BONUS_EVERY_MIN)) : 0
  return { ...c, wait_bonus: bonus }
}

function fromSeed({ minutes_ago, assigned_minutes_ago, resolved_minutes_ago, ...c }, now) {
  const resolved = ago(resolved_minutes_ago, now)
  return withWaitBonus({
    ...c,
    created_at: ago(minutes_ago, now),
    assigned_at: ago(assigned_minutes_ago, now),
    resolved_at: resolved,
    updated_at: resolved || ago(assigned_minutes_ago, now) || ago(minutes_ago, now),
  }, now)
}

// Filled on first use (not at import), so the live build can drop this whole file
let cases = null
const listeners = new Set()

export const getCases = () => {
  if (!cases) {
    const now = Date.now()
    cases = new Map(seed.map((c) => [c.id, fromSeed(c, now)]))
  }
  return cases
}

function commit(next) {
  cases = next
  listeners.forEach((fn) => fn())
}

export const subscribe = (fn) => {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function put(c) {
  commit(new Map(getCases()).set(c.id, c))
  return c
}

export function remove(ids) {
  const next = new Map(getCases())
  ids.forEach((id) => next.delete(id))
  commit(next)
}

function update(id, fields) {
  const c = getCases().get(id)
  if (!c) throw new Error('Case not found')
  return put(withWaitBonus({ ...c, ...fields, updated_at: new Date().toISOString() }))
}

// Same rules as backend/app/cases.py (assign, set_status, set_location), minus the phone calls
const ACTIONS = {
  assign: (id, { unit, eta_minutes }) =>
    update(id, { status: 'assigned', unit, eta_minutes, assigned_at: new Date().toISOString() }),
  status: (id, { status }) =>
    update(id, status === 'open'
      ? { status, unit: null, eta_minutes: null, assigned_at: null, resolved_at: null, callback_status: null }
      : { status, ...(status === 'rescued' || status === 'closed' ? { resolved_at: new Date().toISOString() } : {}) }),
  location: (id, { lat, lng }) => {
    const c = getCases().get(id)
    const reasons = (c?.reasons || []).filter((r) => !r.startsWith('Pin is approximate') && !r.startsWith('Location not confirmed'))
    return update(id, { lat, lng, location_confidence: 'high', reasons })
  },
}

// Stands in for lib.api(): same paths, answered locally
export async function demoApi(path, { method = 'GET', body } = {}) {
  const m = path.match(/^\/api\/cases\/(\d+)(?:\/(\w+))?$/)
  if (m) {
    const [, id, action] = m
    if (!action && method === 'GET') {
      const c = getCases().get(Number(id))
      if (!c) throw new Error('Case not found')
      return c
    }
    if (ACTIONS[action]) return ACTIONS[action](Number(id), body || {})
  }
  throw new Error('Not available in the demo: it needs the live backend.')
}

export function stats(list, now = Date.now()) {
  const calls = list.filter((c) => c.source !== 'social').map((c) => new Date(c.created_at).getTime())
  const buckets = new Map()
  calls.filter((t) => now - t < 10 * 60000).forEach((t) => {
    const b = Math.floor(t / 15000) * 15000
    buckets.set(b, (buckets.get(b) || 0) + 1)
  })
  const open = list.filter((c) => c.status === 'open')
  return {
    series: [...buckets].sort(([a], [b]) => a - b).map(([b, n]) => ({ bucket: new Date(b).toISOString(), calls: n })),
    calls_last_minute: calls.filter((t) => now - t < 60000).length,
    open: open.length,
    assigned: list.filter((c) => c.status === 'assigned').length,
    rescued_24h: list.filter((c) => c.status === 'rescued').length,
    avg_wait_min: open.length ? open.reduce((s, c) => s + (now - new Date(c.created_at).getTime()) / 60000, 0) / open.length : 0,
  }
}

// Harvey surge: replays simulated calls that were scored by the backend ahead of time (surge.json).
export async function runSurge({ count = 300, seconds = 60, onCase, onDone }) {
  const pool = (await import('./surge.json')).default.slice(0, count)
  const gaps = pool.map(() => -Math.log(1 - Math.random())) // arrivals like a real surge, as simulator.py does
  const scale = (seconds * 1000) / gaps.reduce((a, b) => a + b, 0)
  let at = 0
  let nextId = Math.max(3000, ...getCases().keys()) + 1
  const timers = pool.map((c, i) => {
    at += gaps[i] * scale
    return setTimeout(() => {
      const id = nextId++
      const now = new Date().toISOString()
      const added = put({ ...c, id, case_number: `LF-${id + 1000}`, created_at: now, updated_at: now, wait_bonus: 0 })
      onCase?.(added)
      if (i === pool.length - 1) onDone?.()
    }, at)
  })
  return () => { timers.forEach(clearTimeout); onDone?.() }
}
