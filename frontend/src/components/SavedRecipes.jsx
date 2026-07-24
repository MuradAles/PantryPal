import Icon from './Icon.jsx'

/**
 * The list of kept recipes, in the mockup's Chat History treatment.
 *
 * There is one conversation per user, so there is no history to list; the rail
 * holds saved recipes instead. The active row keeps the primary-container
 * highlight and the nudge to the right.
 */
export default function SavedRecipes({ recipes, selectedId, onSelect, onDelete, busyId }) {
  if (recipes.length === 0) {
    return (
      <p className="px-4 text-helper-text font-helper-text text-on-surface-variant">
        Nothing saved yet. Keep a recipe from a reply and it will wait for you here.
      </p>
    )
  }

  return (
    <ul className="space-y-1">
      {recipes.map((item) => {
        const active = item.id === selectedId
        return (
          <li key={item.id} className="group relative">
            <button
              type="button"
              onClick={() => onSelect(item)}
              aria-current={active ? 'true' : undefined}
              className={
                active
                  ? 'w-full flex items-center gap-3 pl-4 pr-10 py-3 bg-primary-container text-on-primary-container rounded-lg font-bold text-left transition-all duration-200 translate-x-1'
                  : 'w-full flex items-center gap-3 pl-4 pr-10 py-3 text-on-surface-variant hover:bg-surface-variant rounded-lg text-left transition-all'
              }
            >
              <Icon name={active ? 'restaurant_menu' : 'history'} className="shrink-0" />
              <span className="truncate">{item.title || 'Untitled recipe'}</span>
            </button>
            <button
              type="button"
              disabled={busyId === item.id}
              onClick={() => onDelete(item)}
              aria-label={`Delete ${item.title || 'this recipe'}`}
              className={
                (active ? 'text-on-primary-container ' : 'text-on-surface-variant ') +
                'absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-full opacity-60 hover:opacity-100 hover:bg-surface-container-high focus:opacity-100 transition-opacity disabled:opacity-30'
              }
            >
              <Icon name="close" className="text-[18px]" />
            </button>
          </li>
        )
      })}
    </ul>
  )
}
