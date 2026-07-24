import { useEffect, useRef } from 'react'
import Message from './Message.jsx'
import Composer from './Composer.jsx'

/** What the assistant is for, shown before the first message. */
function EmptyState() {
  return (
    <div className="empty-state">
      <h2>Tell me what you have, and I will tell you what to cook.</h2>
      <p>
        I answer cooking questions, suggest recipes, and work out meals from the ingredients and
        equipment you actually own. Mention your pan, your allergies or a cuisine you love and I
        will remember it for next time.
      </p>
      <p>
        I stick to food and its neighbours — wine, gear, hosting, restaurants. I do not give
        medical, dietary or food-safety advice.
      </p>
    </div>
  )
}

/** The conversation column: transcript plus the composer. */
export default function Chat({ messages, streaming, error, onSend, onStop }) {
  const bottom = useRef(null)

  // Follow the newest text as it streams in, rather than only on new messages.
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  return (
    <section className="chat" aria-label="Conversation">
      <div className="transcript">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <ol className="messages">
            {messages.map((message) => (
              <Message key={message.id} message={message} />
            ))}
          </ol>
        )}
        <div ref={bottom} />
      </div>

      {error && (
        <p className="stream-error" role="alert">
          {error}
        </p>
      )}

      <Composer disabled={streaming} onSend={onSend} onStop={onStop} />
    </section>
  )
}
