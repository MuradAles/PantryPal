import { useState } from 'react'

/** The message box: Enter sends, Shift+Enter breaks a line, locked while streaming. */
export default function Composer({ disabled, onSend, onStop }) {
  const [draft, setDraft] = useState('')

  function send() {
    const text = draft.trim()
    if (!text || disabled) return
    setDraft('')
    onSend(text)
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      send()
    }
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault()
        send()
      }}
    >
      <label className="visually-hidden" htmlFor="composer-input">
        Message PantryPal
      </label>
      <textarea
        id="composer-input"
        rows={2}
        value={draft}
        disabled={disabled}
        placeholder="What are you cooking?"
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      {disabled ? (
        <button type="button" onClick={onStop}>
          Stop
        </button>
      ) : (
        <button type="submit" disabled={!draft.trim()}>
          Send
        </button>
      )}
    </form>
  )
}
