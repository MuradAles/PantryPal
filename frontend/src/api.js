/** HTTP and SSE calls against the PantryPal backend. */

/** Pull the human-readable reason out of a failed response, with a fallback. */
async function errorDetail(response, fallback) {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // A proxy or crash can answer with something that is not JSON.
  }
  return fallback
}

/** Split one SSE frame into its event name and decoded JSON payload. */
function parseFrame(frame) {
  let name = 'message'
  const data = []
  for (const line of frame.split('\n')) {
    // sse-starlette sends keep-alive comments; they carry no event.
    if (line.startsWith(':')) continue
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
  }
  if (data.length === 0) return null
  try {
    return { name, payload: JSON.parse(data.join('\n')) }
  } catch {
    return null
  }
}

/**
 * Stream one chat turn, invoking handlers as events arrive.
 *
 * EventSource cannot POST, so the stream is read off fetch's body directly and
 * the frames are parsed here.
 */
export async function streamChat({ userId, message, signal, onToken, onDone, onError }) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, message }),
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(await errorDetail(response, 'The assistant is unavailable right now.'))
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

    let boundary
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const frame = parseFrame(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      if (!frame) continue
      if (frame.name === 'token') onToken(frame.payload.text)
      else if (frame.name === 'done') onDone(frame.payload)
      else if (frame.name === 'error') onError(frame.payload.detail)
    }
  }
}

/** Read everything stored about a user. */
export async function fetchProfile(userId) {
  const response = await fetch(`/api/profile/${encodeURIComponent(userId)}`)
  if (!response.ok) throw new Error(await errorDetail(response, 'Could not load your profile.'))
  return response.json()
}

/** Overwrite only the named fields, leaving the rest of the profile alone. */
export async function patchProfile(userId, changes) {
  const response = await fetch(`/api/profile/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  })
  if (!response.ok) throw new Error(await errorDetail(response, 'Could not save that change.'))
  return response.json()
}

/** Erase everything stored about a user. */
export async function deleteProfile(userId) {
  const response = await fetch(`/api/profile/${encodeURIComponent(userId)}`, { method: 'DELETE' })
  if (!response.ok) throw new Error(await errorDetail(response, 'Could not delete your data.'))
}

/** The recipes a user has kept, newest first. */
export async function fetchRecipes(userId) {
  const response = await fetch(`/api/recipes/${encodeURIComponent(userId)}`)
  // A 404 is also what a backend without this route answers, and an empty rail
  // is a better first impression than an error the user cannot act on.
  if (response.status === 404) return []
  if (!response.ok) throw new Error(await errorDetail(response, 'Could not load your saved recipes.'))
  const body = await response.json()
  return Array.isArray(body) ? body : (body.recipes ?? [])
}

/** Keep a recipe from a reply. */
export async function saveRecipe(userId, recipe) {
  const response = await fetch(`/api/recipes/${encodeURIComponent(userId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(recipe),
  })
  if (!response.ok) throw new Error(await errorDetail(response, 'Could not save that recipe.'))
  return response.json()
}

/** Forget one saved recipe. */
export async function deleteRecipe(userId, recipeId) {
  const response = await fetch(
    `/api/recipes/${encodeURIComponent(userId)}/${encodeURIComponent(recipeId)}`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw new Error(await errorDetail(response, 'Could not delete that recipe.'))
}
