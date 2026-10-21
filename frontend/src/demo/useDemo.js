import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { getCases, put, remove, runSurge, stats, subscribe } from './store'

// Same shape as useLive(), fed by the in-browser demo store instead of the /ws socket.
export function useDemo() {
  const cases = useSyncExternalStore(subscribe, getCases)
  const [now, setNow] = useState(Date.now())
  const [surge, setSurge] = useState(false)
  const [alerts, setAlerts] = useState([])
  const stopSurge = useRef(null)

  // Stats refresh every 5 seconds, like the server's stats loop
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 5000)
    return () => { clearInterval(t); stopSurge.current?.() }
  }, [])

  const list = [...cases.values()]
  const liveStats = useMemo(() => stats(list, Date.now()), [cases, now])

  async function startSurge(options) {
    setSurge(true)
    stopSurge.current = await runSurge({
      ...options,
      onCase: (c) => {
        if (c.life_threatening) {
          setAlerts((prev) => [{ key: `${c.id}-${Date.now()}`, case: c }, ...prev].slice(0, 3))
        }
      },
      onDone: () => setSurge(false),
    })
  }

  function clearSimulated() {
    stopSurge.current?.()
    const ids = list.filter((c) => c.source === 'simulated').map((c) => c.id)
    remove(ids)
    setAlerts((prev) => prev.filter((a) => !ids.includes(a.case.id)))
    return { removed: ids.length }
  }

  const dismissAlert = (key) => setAlerts((prev) => prev.filter((a) => a.key !== key))

  return {
    cases, stats: liveStats, features: { gemini: false }, connected: true, surge, alerts, dismissAlert,
    mergeCase: put, startSurge, clearSimulated,
  }
}
