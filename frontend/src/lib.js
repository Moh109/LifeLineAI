// Shared helpers: API calls, priority math (mirrors backend/app/scoring.py), formatting.
import { demoApi } from './demo/store'

// Static demo site (npm run build): sample cases in the browser, no backend. npm run build:live is the real dashboard.
export const DEMO = import.meta.env.MODE === 'demo'

// Dispatch key: typed in once by the dispatcher and kept in this browser only. Never part of the build.
const KEY_STORE = 'lifeline_dispatch_key'

export function getDispatchKey() {
  try {
    return localStorage.getItem(KEY_STORE) || ''
  } catch {
    return ''
  }
}

export function setDispatchKey(key) {
  try {
    localStorage.setItem(KEY_STORE, key)
  } catch {
    // storage blocked (private mode): the key just won't be remembered
  }
}

export async function api(path, { method = 'GET', body } = {}) {
  if (DEMO) return demoApi(path, { method, body })
  const headers = {}
  if (body) headers['Content-Type'] = 'application/json'
  const key = getDispatchKey()
  if (key) headers['X-Dispatch-Key'] = key
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined })
  const data = await res.json().catch(() => ({}))
  if (res.status === 401) window.dispatchEvent(new Event('lifeline:need-key'))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

// Hex values (not CSS vars) because the map draws on a canvas. Keep in sync with styles.css.
export const COLORS = {
  red: '#c8102e',
  orange: '#e8740c',
  yellow: '#7a6a00',
  water: '#2f6fa3',
  ink: '#142430',
  rescued: '#2e7d4f',
}

export const TRIAGE = {
  red: { word: 'Immediate', color: COLORS.red },
  orange: { word: 'Urgent', color: COLORS.orange },
  yellow: { word: 'Delayed', color: COLORS.yellow },
}

const WAIT_BONUS_EVERY_MIN = 10
const WAIT_BONUS_MAX = 20

export function minutesSince(iso, now = Date.now()) {
  if (!iso) return 0
  return Math.max(0, (now - new Date(iso).getTime()) / 60000)
}

export function effectivePriority(c, now = Date.now()) {
  const bonus = c.status === 'open'
    ? Math.min(WAIT_BONUS_MAX, Math.floor(minutesSince(c.created_at, now) / WAIT_BONUS_EVERY_MIN))
    : 0
  return Math.min(100, (c.base_priority || 0) + bonus)
}

export function labelFor(score) {
  if (score >= 60) return 'red'
  if (score >= 35) return 'orange'
  return 'yellow'
}

export function waitText(iso, now = Date.now()) {
  const m = minutesSince(iso, now)
  if (m < 1) return 'just now'
  if (m < 60) return `${Math.floor(m)} min`
  const h = Math.floor(m / 60)
  return `${h} h ${Math.floor(m % 60)} min`
}

export function clockTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export const SOURCE_TAGS = {
  simulated: 'Simulated',
  social: 'From a post',
  dropped_call: 'Dropped call, rebuilt',
}

// Only flood cases show water depth: a depth was given, water is rising, or the backend scored it as a flood
// (a gunshot or a sprained ankle with "no water" shouldn't talk about water at all)
const DEPTHS = ['ankle', 'knee', 'waist', 'chest', 'roof']
export function isWaterCase(c) {
  return DEPTHS.includes(c.water_level) || Boolean(c.water_rising)
    || (c.reasons || []).some((r) => r.startsWith('Unknown water level'))
}

export const WATER_WORDS = {
  ankle: 'Ankle-deep', knee: 'Knee-deep', waist: 'Waist-deep', chest: 'Chest-deep', roof: 'On the roof',
  none: 'No water', unknown: 'Depth unknown',
}

export const UNITS = ['Boat B-1', 'Boat B-2', 'Boat B-3', 'High-water truck T-7', 'High-water truck T-9', 'Volunteer boat V-4']

// Sort: waiting cases by priority, then assigned, then resolved
export function sortCases(list, now = Date.now()) {
  const rank = { open: 0, assigned: 1, rescued: 2, closed: 3 }
  return [...list].sort((a, b) => {
    if (rank[a.status] !== rank[b.status]) return rank[a.status] - rank[b.status]
    if (a.status === 'open') {
      const d = effectivePriority(b, now) - effectivePriority(a, now)
      return d || new Date(a.created_at) - new Date(b.created_at)
    }
    return new Date(b.updated_at) - new Date(a.updated_at)
  })
}
