/** The browser-local identity the backend remembers a user by. */

const STORAGE_KEY = 'pantrypal.user_id'

/** Return this browser's user id, minting and storing one on first visit. */
export function getUserId() {
  let id = null
  try {
    id = localStorage.getItem(STORAGE_KEY)
  } catch {
    // Private mode or blocked storage: fall through to a per-session id so the
    // app still works, it just will not remember across reloads.
  }
  if (id) return id

  id = crypto.randomUUID()
  try {
    localStorage.setItem(STORAGE_KEY, id)
  } catch {
    // Nothing to do; the id lives for this page load only.
  }
  return id
}
