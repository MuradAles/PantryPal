/**
 * The allergen notice, as fixed app-owned text.
 *
 * The wording lives here rather than in a prompt so that it is identical on every
 * message that carries it. The model can neither write it, reword it, nor skip it.
 */
export default function AllergenNotice() {
  return (
    <aside className="allergen-notice" role="note">
      <strong>Allergen notice:</strong> recipes and ingredients mentioned here may contain or come
      into contact with common allergens. Check labels and confirm with anyone you are cooking for.
    </aside>
  )
}
