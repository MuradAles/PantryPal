import { useCallback, useEffect, useState } from 'react'
import { deleteProfile, fetchProfile, patchProfile } from '../api.js'
import Icon from './Icon.jsx'

// Every field the backend stores gets a group, so the panel is a complete account
// of what is held about the user. There is deliberately no medical field to show.
// Cookware is tags like the rest: we store the name of a pan, never a quantity,
// so the mockup's pantry table with amounts would be inventing data.
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
    <section data-field={group.field}>
      <h4 className="font-label-caps text-label-caps text-primary uppercase mb-3">{group.label}</h4>
      {values.length === 0 ? (
        <p className="text-helper-text font-helper-text text-on-surface-variant">{group.empty}</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {values.map((value) => (
            <li
              key={value}
              className="flex items-center gap-1 pl-3 pr-1 py-1 bg-secondary-container text-on-secondary-container rounded-full text-xs font-bold border border-secondary/20"
            >
              <span>{value}</span>
              <button
                type="button"
                disabled={busy}
                aria-label={`Remove ${value} from ${group.label}`}
                onClick={() => onRemove(group.field, value)}
                className="rounded-full p-0.5 hover:bg-secondary/20 transition-colors disabled:opacity-40 flex items-center"
              >
                <Icon name="close" className="text-[14px]" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** What the assistant knows about you, editable, with a delete-everything control. */
export default function ProfilePanel({ userId, refreshKey, onDeleted }) {
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
      onDeleted?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div aria-label="What PantryPal knows about you">
      <div className="mb-8">
        <h3 className="font-headline-md text-headline-md text-on-background mb-2">Memory Bank</h3>
        <p className="text-helper-text font-helper-text text-on-surface-variant italic">
          Learned from the conversation. Edit or erase any of it.
        </p>
      </div>

      <div className="space-y-6">
        {GROUPS.map((group) => (
          <Group
            key={group.field}
            group={group}
            values={profile[group.field] ?? []}
            busy={busy}
            onRemove={removeTag}
          />
        ))}
      </div>

      {error && (
        <p
          role="alert"
          className="mt-6 bg-error-container text-on-error-container rounded-lg p-3 text-helper-text font-helper-text"
        >
          {error}
        </p>
      )}

      {/* Kept in the panel body rather than behind a menu: erasure has to be as
          easy to find as the data it erases, at every width. */}
      <section className="mt-8">
        {confirming ? (
          <div className="border border-error/40 rounded-lg p-4">
            <p role="alert" className="text-helper-text font-helper-text text-on-surface mb-4">
              Delete everything PantryPal has stored about you? This cannot be undone.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={deleteEverything}
                className="px-4 py-2 bg-error text-on-error rounded-lg font-label-caps text-label-caps uppercase hover:opacity-90 transition-opacity disabled:opacity-50"
              >
                Yes, delete everything
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => setConfirming(false)}
                className="px-4 py-2 border border-outline text-on-surface-variant rounded-lg font-label-caps text-label-caps uppercase hover:bg-surface-variant transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={() => setConfirming(true)}
            className="w-full py-2 border border-outline text-on-surface-variant rounded-lg font-label-caps text-label-caps uppercase hover:bg-surface-variant transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <Icon name="delete" className="text-[18px]" />
            Delete everything about me
          </button>
        )}
      </section>
    </div>
  )
}
