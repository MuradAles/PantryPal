import { useCallback, useEffect, useRef, useState } from 'react'
import BottomNav from './components/BottomNav.jsx'
import Chat from './components/Chat.jsx'
import ProfilePanel from './components/ProfilePanel.jsx'
import RecipeCard from './components/RecipeCard.jsx'
import SavedRecipes from './components/SavedRecipes.jsx'
import TopAppBar from './components/TopAppBar.jsx'
import Icon from './components/Icon.jsx'
import { deleteRecipe, fetchRecipes, saveRecipe, streamChat } from './api.js'
import { getUserId } from './userId.js'

/** A blank turn in the transcript. */
function newMessage(role, text) {
  return {
    id: crypto.randomUUID(),
    role,
    text,
    allergenNotice: false,
    sources: [],
    recipe: null,
    streaming: role === 'assistant',
    error: null,
  }
}

/**
 * Flatten a saved-recipe row to { id, title, recipe }.
 *
 * Tolerates the row being the recipe itself, so the rail still works if the
 * backend stores recipes flat rather than wrapped.
 */
function savedItem(row, index) {
  const recipe = row.recipe ?? row
  return {
    id: row.id ?? `${index}`,
    title: row.title ?? recipe.title ?? 'Untitled recipe',
    recipe,
  }
}

export default function App() {
  // Read once: a new id mid-session would silently orphan the user's memory.
  const [userId] = useState(getUserId)
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [view, setView] = useState('chat')
  const [helpOpen, setHelpOpen] = useState(false)
  const [recipes, setRecipes] = useState([])
  const [selected, setSelected] = useState(null)
  const [recipesError, setRecipesError] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const abort = useRef(null)

  const update = useCallback((id, changes) => {
    setMessages((current) =>
      current.map((message) => (message.id === id ? { ...message, ...changes } : message)),
    )
  }, [])

  const loadRecipes = useCallback(async () => {
    try {
      const rows = await fetchRecipes(userId)
      setRecipes(rows.map(savedItem))
      setRecipesError(null)
    } catch (err) {
      setRecipesError(err.message)
    }
  }, [userId])

  useEffect(() => {
    loadRecipes()
  }, [loadRecipes])

  async function send(text) {
    const reply = newMessage('assistant', '')
    setMessages((current) => [...current, newMessage('user', text), reply])
    setStreaming(true)
    setError(null)
    setHelpOpen(false)

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
        // The three things the model is not trusted to place itself: the notice,
        // the sources, and the shape of the recipe card.
        onDone: (payload) =>
          update(reply.id, {
            allergenNotice: Boolean(payload.allergen_notice),
            sources: payload.sources ?? [],
            recipe: payload.recipe ?? null,
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

  async function keepRecipe(recipe) {
    try {
      await saveRecipe(userId, recipe)
      setRecipesError(null)
      await loadRecipes()
    } catch (err) {
      setRecipesError(err.message)
    }
  }

  async function forgetRecipe(item) {
    setBusyId(item.id)
    try {
      await deleteRecipe(userId, item.id)
      if (selected?.id === item.id) setSelected(null)
      setRecipesError(null)
      await loadRecipes()
    } catch (err) {
      setRecipesError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  function openRecipe(item) {
    setSelected(item)
    setView('recipes')
  }

  const savedTitles = new Set(recipes.map((item) => item.title))

  return (
    <>
      <TopAppBar
        view={view}
        onNavigate={setView}
        helpOpen={helpOpen}
        onToggleHelp={() => setHelpOpen((open) => !open)}
      />

      {/* The mockup's Chat History rail. There is one conversation per user, so
          it lists saved recipes instead. */}
      <aside className="hidden xl:flex fixed left-0 top-16 h-[calc(100vh-64px)] w-72 bg-surface-container-low border-r border-outline-variant flex-col p-base overflow-y-auto">
        <div className="px-4 py-6 mb-4">
          <p className="font-headline-md text-headline-md text-primary">Saved Recipes</p>
          <p className="text-helper-text font-helper-text text-on-surface-variant">
            Everything you have kept from our chats.
          </p>
        </div>
        <nav className="flex-1" aria-label="Saved recipes">
          <SavedRecipes
            recipes={recipes}
            selectedId={selected?.id}
            onSelect={openRecipe}
            onDelete={forgetRecipe}
            busyId={busyId}
          />
        </nav>
      </aside>

      <main className="mt-16 mb-20 xl:ml-72 xl:mr-80 px-container-padding-mobile md:px-container-padding-desktop flex flex-col items-center">
        <div className={`max-w-max-width-content w-full py-12 ${view === 'chat' ? 'pb-40' : ''}`}>
          {view === 'chat' && (
            <Chat
              messages={messages}
              streaming={streaming}
              error={error}
              helpOpen={helpOpen}
              savedTitles={savedTitles}
              onSend={send}
              onStop={() => abort.current?.abort()}
              onSave={keepRecipe}
            />
          )}

          {view === 'recipes' && (
            <section aria-label="Saved recipes">
              <div className="flex items-center justify-between gap-4 mb-6">
                <h2 className="font-headline-md text-headline-md text-on-background">
                  {selected ? selected.title : 'Saved Recipes'}
                </h2>
                {selected && (
                  <button
                    type="button"
                    onClick={() => setSelected(null)}
                    className="flex items-center gap-2 px-3 py-1.5 border border-outline text-on-surface-variant rounded-full font-label-caps text-label-caps uppercase hover:bg-surface-variant transition-colors"
                  >
                    <Icon name="arrow_back" className="text-[16px]" />
                    All recipes
                  </button>
                )}
              </div>

              {recipesError && (
                <p
                  role="alert"
                  className="mb-6 bg-error-container text-on-error-container rounded-lg p-4 text-helper-text font-helper-text"
                >
                  {recipesError}
                </p>
              )}

              {selected ? (
                // A saved card always names ingredients, so it always carries the
                // notice — same app-owned string, same boolean discipline.
                <RecipeCard recipe={selected.recipe} allergenNotice />
              ) : (
                <SavedRecipes
                  recipes={recipes}
                  selectedId={selected?.id}
                  onSelect={openRecipe}
                  onDelete={forgetRecipe}
                  busyId={busyId}
                />
              )}
            </section>
          )}

          {view === 'profile' && (
            <>
              <div className="xl:hidden">
                <ProfilePanel userId={userId} refreshKey={refreshKey} onDeleted={loadRecipes} />
              </div>
              <p className="hidden xl:block text-helper-text font-helper-text text-on-surface-variant">
                Your Memory Bank is in the panel on the right.
              </p>
            </>
          )}
        </div>
      </main>

      {/* The mockup's "what I know about you" panel. */}
      <aside className="hidden xl:flex fixed right-0 top-16 h-[calc(100vh-64px)] w-80 bg-surface border-l border-outline-variant flex-col p-6 overflow-y-auto">
        <ProfilePanel userId={userId} refreshKey={refreshKey} onDeleted={loadRecipes} />
      </aside>

      <BottomNav view={view} onNavigate={setView} />
    </>
  )
}
