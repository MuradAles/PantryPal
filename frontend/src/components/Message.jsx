import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import AllergenNotice from './AllergenNotice.jsx'

/** Compact list of the web results an answer drew on. */
function Sources({ sources }) {
  return (
    <aside className="sources">
      <h3>Sources</h3>
      <ul>
        {sources.map((source) => (
          <li key={source.url}>
            <a href={source.url} target="_blank" rel="noreferrer noopener">
              {source.title || source.url}
            </a>
          </li>
        ))}
      </ul>
    </aside>
  )
}

/** One turn in the transcript: the user's words, or the assistant's with its chrome. */
export default function Message({ message }) {
  if (message.role === 'user') {
    return (
      <li className="message message-user">
        <div className="bubble">{message.text}</div>
      </li>
    )
  }

  return (
    <li className="message message-assistant">
      <div className="bubble">
        {/* Markdown because recipes come back as headings, ingredient lists and
            numbered steps. */}
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>

        {message.streaming && (
          <p className="generating" aria-live="polite">
            Thinking<span aria-hidden="true">…</span>
          </p>
        )}

        {/* Chrome, driven by the flag on the done event and never by anything in
            message.text. Counsel requires the notice to be consistent, which it
            only is if the app renders it. */}
        {message.allergenNotice && <AllergenNotice />}

        {message.sources.length > 0 && <Sources sources={message.sources} />}

        {message.error && (
          <p className="stream-error" role="alert">
            {message.error}
          </p>
        )}
      </div>
    </li>
  )
}
