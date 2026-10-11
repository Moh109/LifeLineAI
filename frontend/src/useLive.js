import { useEffect, useRef, useState } from 'react'
import { getDispatchKey } from './lib'

// Live connection to the backend: one snapshot, then case/stat/alert events.
export function useLive() {
  const [cases, setCases] = useState(() => new Map())
  const [stats, setStats] = useState(null)
  const [features, setFeatures] = useState(null)
  const [connected, setConnected] = useState(false)
  const [surge, setSurge] = useState(false)
  const [alerts, setAlerts] = useState([])
  const retry = useRef(0)

  useEffect(() => {
    let ws
    let closed = false
    let pingTimer

    function connect() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const key = getDispatchKey()
      ws = new WebSocket(`${proto}://${location.host}/ws${key ? `?key=${encodeURIComponent(key)}` : ''}`)
      ws.onopen = () => {
        setConnected(true)
        retry.current = 0
        pingTimer = setInterval(() => ws.readyState === 1 && ws.send('ping'), 20000)
      }
      ws.onclose = () => {
        setConnected(false)
        clearInterval(pingTimer)
        if (!closed) setTimeout(connect, Math.min(8000, 500 * 2 ** retry.current++))
      }
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data)
        switch (msg.type) {
          case 'snapshot':
            setCases(new Map(msg.cases.map((c) => [c.id, c])))
            setStats(msg.stats)
            setFeatures(msg.features)
            break
          case 'case_upsert':
            setCases((prev) => new Map(prev).set(msg.case.id, msg.case))
            break
          case 'stats':
            setStats(msg.stats)
            break
          case 'alert':
            setAlerts((prev) => [{ key: `${msg.case.id}-${Date.now()}`, case: msg.case }, ...prev].slice(0, 3))
            break
          case 'surge':
            setSurge(msg.state === 'started')
            break
          case 'reset':
            setCases((prev) => {
              const next = new Map(prev)
              msg.removed.forEach((id) => next.delete(id))
              return next
            })
            setAlerts((prev) => prev.filter((a) => !msg.removed.includes(a.case.id)))
            break
          default:
        }
      }
    }

    connect()
    return () => {
      closed = true
      clearInterval(pingTimer)
      ws?.close()
    }
  }, [])

  const dismissAlert = (key) => setAlerts((prev) => prev.filter((a) => a.key !== key))
  const mergeCase = (c) => setCases((prev) => new Map(prev).set(c.id, c))

  return { cases, stats, features, connected, surge, alerts, dismissAlert, mergeCase }
}
