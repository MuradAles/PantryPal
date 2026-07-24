import { useState } from 'react'
import Icon from './Icon.jsx'

/**
 * The message box: Enter sends, Shift+Enter breaks a line, locked while streaming.
 *
 * The mockup has no composer, so this is built from its own parts — the card
 * surface, the outline border and the round primary button the FAB used.
 */
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
    // Sits above the mobile tab bar, and hard against the bottom once the rails
    // take over from it.
    <div className="fixed bottom-16 xl:bottom-0 left-0 right-0 xl:left-72 xl:right-80 z-40 bg-gradient-to-t from-background via-background to-transparent px-container-padding-mobile md:px-container-padding-desktop pt-6 pb-4">
      <form
        className="max-w-max-width-content mx-auto flex items-end gap-inline-gap bg-surface-container-lowest border border-outline-variant rounded-xl p-2 recipe-card-shadow"
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
          rows={1}
          value={draft}
          disabled={disabled}
          placeholder="What are you cooking?"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          className="flex-1 resize-none bg-transparent px-3 py-2.5 font-ui-main text-ui-main text-on-surface placeholder:text-on-surface-variant/70 focus:outline-none disabled:opacity-60"
        />
        {disabled ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop generating"
            className="bg-surface-variant text-on-surface-variant w-10 h-10 rounded-full shrink-0 flex items-center justify-center hover:opacity-90 transition-transform active:scale-95"
          >
            <Icon name="stop" filled />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!draft.trim()}
            aria-label="Send message"
            className="bg-primary text-on-primary w-10 h-10 rounded-full shrink-0 flex items-center justify-center shadow-xl hover:scale-105 transition-transform active:scale-95 disabled:opacity-40 disabled:hover:scale-100 disabled:shadow-none"
          >
            <Icon name="arrow_upward" />
          </button>
        )}
      </form>
    </div>
  )
}
