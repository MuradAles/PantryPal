import Icon from './Icon.jsx'

// Pantry and Favorites are dropped with the rest of the cut scope. Profile is
// here because below xl both side rails are hidden, and the delete-everything
// control inside the profile has to stay reachable at every width.
const TABS = [
  { view: 'chat', label: 'Chat', icon: 'chat' },
  { view: 'recipes', label: 'Recipes', icon: 'restaurant_menu' },
  { view: 'profile', label: 'Profile', icon: 'person' },
]

/** The mobile tab bar, shown wherever the side rails are not. */
export default function BottomNav({ view, onNavigate }) {
  return (
    <nav
      className="xl:hidden fixed bottom-0 w-full z-50 flex justify-around items-center h-16 bg-surface border-t border-outline-variant px-4 pb-safe shadow-lg"
      aria-label="Sections"
    >
      {TABS.map((tab) => (
        <button
          key={tab.view}
          type="button"
          aria-current={view === tab.view ? 'page' : undefined}
          onClick={() => onNavigate(tab.view)}
          className={
            view === tab.view
              ? 'flex flex-col items-center justify-center text-primary font-bold transition-opacity scale-90 duration-100'
              : 'flex flex-col items-center justify-center text-on-surface-variant hover:opacity-80 transition-opacity'
          }
        >
          <Icon name={tab.icon} />
          <span className="font-label-caps text-label-caps uppercase text-[10px]">{tab.label}</span>
        </button>
      ))}
    </nav>
  )
}
