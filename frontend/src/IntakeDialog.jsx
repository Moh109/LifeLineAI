import { useEffect, useRef, useState } from 'react'
import { api } from './lib'

const EXAMPLE =
  'PLEASE HELP my grandparents are stuck at 7322 Endicott Ln in Meyerland, water is up to their waist and rising. My grandpa uses oxygen and the power is out. Their number is 713-555-0187'

export default function IntakeDialog({ open, onClose, onCreated, notify }) {
  const ref = useRef(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const c = await api('/api/intake/text', { method: 'POST', body: { text } })
      onCreated(c)
      notify(`Added ${c.case_number} from the post.`)
      setText('')
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <dialog ref={ref} className="intake" onClose={onClose}>
      <form onSubmit={submit}>
        <h2>Add a request from a post</h2>
        <p className="muted">
          During Harvey, people posted their addresses on social media when 911 was full. Paste a post or text message and
          Gemini turns it into a case in the same queue.
        </p>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} required minLength={10}
          placeholder="Paste the post here" aria-label="Post text" />
        {!text && <button type="button" className="link" onClick={() => setText(EXAMPLE)}>Use an example post</button>}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="actions">
          <button type="submit" className="primary" disabled={busy || text.length < 10}>{busy ? 'Reading the post' : 'Add to queue'}</button>
          <button type="button" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </dialog>
  )
}
