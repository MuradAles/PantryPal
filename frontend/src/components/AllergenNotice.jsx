import Icon from './Icon.jsx'

/**
 * The allergen notice, as fixed app-owned text.
 *
 * The wording lives here rather than in a prompt so that it is identical on every
 * message that carries it. The model can neither write it, reword it, nor skip it.
 * The mockup shows model-written wording naming a specific ingredient — that is
 * exactly what counsel ruled out, so only the box around the text is taken from it.
 */
export default function AllergenNotice() {
  return (
    <aside
      role="note"
      className="bg-secondary-container/30 border border-secondary/20 rounded-lg p-4 flex items-start gap-3 mb-8"
    >
      <Icon name="info" className="text-secondary shrink-0" />
      <span className="text-helper-text font-helper-text text-on-secondary-fixed-variant">
        <strong className="font-bold">Allergen notice:</strong> recipes and ingredients mentioned
        here may contain or come into contact with common allergens. Check labels and confirm with
        anyone you are cooking for.
      </span>
    </aside>
  )
}
