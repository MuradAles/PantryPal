import { useCallback, useEffect, useState } from 'react'
import { deleteProfile, fetchProfile, patchProfile } from '../api.js'

// Every field the backend stores gets a group, so the panel is a complete account
// of what is held about the user. There is deliberately no medical field to show.
const GROUPS = [
  { field: 'cookware', label: 'Cookware', empty: 'Nothing learned yet — tell me what you cook with.' },
  { field: 'likes', label: 'Likes', empty: 'Nothing learned yet — tell me what you enjoy.' },
  { field: 'dislikes', label: 'Dislikes', empty: 'Nothing learned yet.' },
  { field: 'avoid', label: 'Avoids', empty: 'Nothing learned yet — tell me what to keep off your plate.' },
]

const EMPTY = { cookware: [], likes: [], dislikes: [], avoid: [] }

/** One group of tags, each individually removable. */
function Group({ group, values, busy, onRemove }) {
  return (
    // data-field lets styling target a group by name. Without it the only hook is
    // nth-of-type, which silently reassigns colours the moment GROUPS is reordered.
    <section className="profile-group" data-field={group.field}>
      <h3>{group.label}</h3>
      {values.length === 0 ? (
        <p className="profile-empty">{group.empty}</p>
      ) : (
        <ul className="tags">
          {values.map((value) => (
            <li key={value} className="tag">
              <span>{value}</span>
              <button
                type="button"
                disabled={busy}
                aria-label={`Remove ${value} from ${group.label}`}
                onClick={() => onRemove(group.field, value)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** What the assistant knows about you, editable, with a delete-everything control. */
export default function ProfilePanel({ userId, refreshKey }) {
  const [profile, setProfile] = useState(EMPTY)
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const next = await fetchProfile(userId)
      setProfile({ ...EMPTY, ...next })
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [userId])

  // refreshKey changes after every assistant turn, which is how a tag the model
  // just learned shows up without a reload.
  useEffect(() => {
    load()
  }, [load, refreshKey])

  async function removeTag(field, value) {
    const remaining = profile[field].filter((item) => item !== value)
    setBusy(true)
    try {
      // PATCH carries only the edited field, so removing one tag cannot clear the
      // others if the request races another write.
      const next = await patchProfile(userId, { [field]: remaining })
      setProfile({ ...EMPTY, ...next })
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function deleteEverything() {
    setBusy(true)
    try {
      await deleteProfile(userId)
      setProfile(EMPTY)
      setConfirming(false)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="profile" aria-label="What PantryPal knows about you">
      <h2>What I know about you</h2>
      <p className="profile-note">Learned from the conversation. Edit or erase any of it.</p>

      {GROUPS.map((group) => (
        <Group
          key={group.field}
          group={group}
          values={profile[group.field] ?? []}
          busy={busy}
          onRemove={removeTag}
        />
      ))}

      {error && (
        <p className="stream-error" role="alert">
          {error}
        </p>
      )}

      {/* Kept in the panel body rather than behind a menu: erasure has to be as
          easy to find as the data it erases. */}
      <section className="profile-delete">
        {confirming ? (
          <>
            <p role="alert">Delete everything PantryPal has stored about you? This cannot be undone.</p>
            <button type="button" disabled={busy} onClick={deleteEverything}>
              Yes, delete everything
            </button>
            <button type="button" disabled={busy} onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </>
        ) : (
          <button type="button" disabled={busy} onClick={() => setConfirming(true)}>
            Delete everything about me
          </button>
        )}
      </section>
    </aside>
  )
}
