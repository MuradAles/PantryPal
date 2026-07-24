import { useEffect, useRef } from 'react'
import Message from './Message.jsx'
import Composer from './Composer.jsx'

/** What the assistant is for, shown before the first message and behind the help button. */
export function Intro() {
  return (
    <div className="bg-surface-container-lowest border border-outline-variant/30 rounded-xl p-8 recipe-card-shadow">
      <h2 className="font-display-lg text-display-lg-mobile md:text-display-lg text-on-background mb-6">
        Tell me what you have, and I will tell you what to cook.
      </h2>
      <p className="font-recipe-body text-recipe-body leading-relaxed mb-4">
        I answer cooking questions, suggest recipes, and work out meals from the ingredients and
        equipment you actually own. Mention your pan, your allergies or a cuisine you love and I
        will remember it for next time.
      </p>
      <p className="text-helper-text font-helper-text text-on-surface-variant">
        I stick to food and its neighbours — wine, gear, hosting, restaurants. I do not give
        medical, dietary or food-safety advice.
      </p>
    </div>
  )
}

/** The conversation column: transcript plus the composer. */
export default function Chat({ messages, streaming, error, helpOpen, savedTitles, onSend, onStop, onSave }) {
  const bottom = useRef(null)

  // Follow the newest text as it streams in, rather than only on new messages.
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  return (
    <section aria-label="Conversation">
      {(messages.length === 0 || helpOpen) && <Intro />}

      {messages.length > 0 && (
        <ol className="flex flex-col space-y-8 mt-8">
          {messages.map((message) => (
            <Message
              key={message.id}
              message={message}
              onSave={message.recipe ? onSave : undefined}
              saved={Boolean(message.recipe?.title && savedTitles.has(message.recipe.title))}
            />
          ))}
        </ol>
      )}

      {error && (
        <p
          role="alert"
          className="mt-8 bg-error-container text-on-error-container rounded-lg p-4 text-helper-text font-helper-text"
        >
          {error}
        </p>
      )}

      <div ref={bottom} />

      <Composer disabled={streaming} onSend={onSend} onStop={onStop} />
    </section>
  )
}
