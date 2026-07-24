import Icon from './Icon.jsx'

// Chat and Recipes only: Groceries and Favorites are in the mockup but were cut
// in SCOPING.md, and a nav item that leads nowhere is worse than one less item.
const LINKS = [
  { view: 'chat', label: 'Chat' },
  { view: 'recipes', label: 'Recipes' },
]

/** The fixed top bar: wordmark, desktop nav, help toggle and avatar. */
export default function TopAppBar({ view, onNavigate, helpOpen, onToggleHelp }) {
  return (
    <header className="bg-surface border-b border-outline-variant fixed top-0 z-50 flex justify-between items-center w-full px-container-padding-mobile md:px-container-padding-desktop h-16">
      <div className="flex items-center gap-4">
        <span className="text-headline-md font-headline-md text-primary">PantryPal</span>
      </div>

      <nav className="hidden md:flex gap-8 items-center h-full" aria-label="Sections">
        {LINKS.map((link) => (
          <button
            key={link.view}
            type="button"
            aria-current={view === link.view ? 'page' : undefined}
            onClick={() => onNavigate(link.view)}
            className={
              view === link.view
                ? 'text-primary font-bold transition-colors px-2 py-1 rounded'
                : 'text-on-surface-variant hover:bg-surface-container-low transition-colors px-2 py-1 rounded'
            }
          >
            {link.label}
          </button>
        ))}
      </nav>

      <div className="flex items-center gap-4">
        <button
          type="button"
          aria-expanded={helpOpen}
          aria-label="What PantryPal can help with"
          onClick={onToggleHelp}
          className="text-primary hover:bg-surface-container-low p-2 rounded-full transition-colors flex items-center"
        >
          <Icon name="psychology_alt" />
        </button>
        {/* The mockup's avatar is a hotlinked photo of a terracotta pot. Drawn as
            a glyph instead so the app owns the asset and cannot 404. */}
        <span className="w-8 h-8 rounded-full border border-outline-variant bg-primary-fixed text-on-primary-fixed flex items-center justify-center shrink-0">
          <Icon name="soup_kitchen" className="text-[18px]" />
        </span>
      </div>
    </header>
  )
}
