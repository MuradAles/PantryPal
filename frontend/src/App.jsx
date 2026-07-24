import { useCallback, useRef, useState } from 'react'
import Chat from './components/Chat.jsx'
import ProfilePanel from './components/ProfilePanel.jsx'
import { streamChat } from './api.js'
import { getUserId } from './userId.js'

/** A blank turn in the transcript. */
function newMessage(role, text) {
  return {
    id: crypto.randomUUID(),
    role,
    text,
    allergenNotice: false,
    sources: [],
    streaming: role === 'assistant',
    error: null,
  }
}

export default function App() {
  // Read once: a new id mid-session would silently orphan the user's memory.
  const [userId] = useState(getUserId)
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const abort = useRef(null)

  const update = useCallback((id, changes) => {
    setMessages((current) =>
      current.map((message) => (message.id === id ? { ...message, ...changes } : message)),
    )
  }, [])

  async function send(text) {
    const reply = newMessage('assistant', '')
    setMessages((current) => [...current, newMessage('user', text), reply])
    setStreaming(true)
    setError(null)

    const controller = new AbortController()
    abort.current = controller

    try {
      await streamChat({
        userId,
        message: text,
        signal: controller.signal,
        onToken: (chunk) =>
          setMessages((current) =>
            current.map((message) =>
              message.id === reply.id ? { ...message, text: message.text + chunk } : message,
            ),
          ),
        // The two things the model is not trusted to produce itself.
        onDone: (payload) =>
          update(reply.id, {
            allergenNotice: Boolean(payload.allergen_notice),
            sources: payload.sources ?? [],
          }),
        onError: (detail) => update(reply.id, { error: detail }),
      })
    } catch (err) {
      // Stopping is a user action, not a failure, so the partial reply stands.
      if (err.name !== 'AbortError') {
        setError(err.message)
        setMessages((current) => current.filter((message) => message.id !== reply.id || message.text))
      }
    } finally {
      abort.current = null
      update(reply.id, { streaming: false })
      setStreaming(false)
      // The turn may have taught the assistant something; show it immediately.
      setRefreshKey((key) => key + 1)
    }
  }

  return (
    <main className="app">
      <header className="app-header">
        <h1>PantryPal</h1>
      </header>
      <div className="columns">
        <Chat
          messages={messages}
          streaming={streaming}
          error={error}
          onSend={send}
          onStop={() => abort.current?.abort()}
        />
        <ProfilePanel userId={userId} refreshKey={refreshKey} />
      </div>
    </main>
  )
}
