import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import AllergenNotice from './AllergenNotice.jsx'
import Icon from './Icon.jsx'
import RecipeCard from './RecipeCard.jsx'
import SourceChips from './SourceChips.jsx'

/** One turn in the transcript: the user's words, or the assistant's with its chrome. */
export default function Message({ message, onSave, saved }) {
  if (message.role === 'user') {
    return (
      <li className="flex justify-end">
        <div className="bg-primary-container text-on-primary-container px-6 py-4 rounded-xl rounded-tr-none max-w-[80%] shadow-sm whitespace-pre-wrap">
          {message.text}
        </div>
      </li>
    )
  }

  return (
    <li className="flex flex-col">
      <div className="flex items-center gap-2 mb-4 text-primary">
        <Icon name="auto_awesome" />
        <span className="font-label-caps text-label-caps">PANTRYPAL ASSISTANT</span>
      </div>

      {/* Markdown because the prose comes back with emphasis and the occasional
          list even when the structured recipe is what carries the detail. */}
      <div className="prose-recipe font-recipe-body text-recipe-body leading-relaxed mb-8">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
      </div>

      {message.streaming && (
        <p className="text-helper-text font-helper-text text-on-surface-variant mb-8" aria-live="polite">
          Thinking<span aria-hidden="true">…</span>
        </p>
      )}

      {/* The recipe card carries the notice and the sources itself when there is
          one, so they are not drawn twice. */}
      {message.recipe ? (
        <RecipeCard
          recipe={message.recipe}
          sources={message.sources}
          allergenNotice={message.allergenNotice}
          onSave={onSave}
          saved={saved}
        />
      ) : (
        <>
          {/* Chrome, driven by the flag on the done event and never by anything in
              message.text. Counsel requires the notice to be consistent, which it
              only is if the app renders it. */}
          {message.allergenNotice && <AllergenNotice />}
          {message.sources.length > 0 && <SourceChips sources={message.sources} />}
        </>
      )}

      {message.error && (
        <p
          role="alert"
          className="mt-4 bg-error-container text-on-error-container rounded-lg p-4 text-helper-text font-helper-text"
        >
          {message.error}
        </p>
      )}
    </li>
  )
}
