import { Fragment } from 'react'
import AllergenNotice from './AllergenNotice.jsx'
import Icon from './Icon.jsx'
import SourceChips from './SourceChips.jsx'

/**
 * The 35 MINS / EASY / SERVES 4 row.
 *
 * The backend sends numbers and a lowercase difficulty, and leaves out anything
 * the model did not actually know. Each part it did send gets a slot; the
 * bullets only go between the ones that survived, so a recipe with just a time
 * does not render a row of orphaned separators.
 */
function MetaRow({ recipe }) {
  const minutes = recipe.time_mins
  const parts = [
    minutes ? `${minutes} ${minutes === 1 ? 'MIN' : 'MINS'}` : null,
    recipe.difficulty || null,
    recipe.serves ? `SERVES ${recipe.serves}` : null,
  ].filter(Boolean)
  if (parts.length === 0) return null

  return (
    <div className="flex justify-center flex-wrap gap-4 text-on-surface-variant font-label-caps text-label-caps uppercase tracking-widest">
      {parts.map((part, index) => (
        <Fragment key={part}>
          {index > 0 && <span aria-hidden="true">•</span>}
          <span>{part}</span>
        </Fragment>
      ))}
    </div>
  )
}

/**
 * A structured recipe, rendered to the mockup's card.
 *
 * Every field is optional: the model fills this in and a section it left empty
 * is simply not drawn, rather than printing an empty heading. The hero image
 * from the mockup is gone — nothing generates one, and the title block takes
 * the space it would have had.
 */
export default function RecipeCard({ recipe, sources = [], allergenNotice = false, onSave, saved }) {
  if (!recipe) return null

  const ingredients = recipe.ingredients ?? []
  const steps = recipe.steps ?? []
  // The card's own sources when the backend attaches them, otherwise the ones
  // the done event reported for the turn as a whole.
  const links = (recipe.sources?.length ? recipe.sources : sources).filter((source) => source?.url)

  return (
    <article className="recipe-card-shadow bg-surface-container-lowest rounded-xl p-6 md:p-8 border border-outline-variant/30">
      <header className="mb-10 pt-6 text-center relative">
        {onSave && (
          <button
            type="button"
            disabled={saved}
            onClick={() => onSave(recipe)}
            aria-label={saved ? 'Recipe saved' : 'Save this recipe'}
            className="absolute right-0 top-0 text-primary hover:bg-surface-container-low disabled:hover:bg-transparent p-2 rounded-full transition-colors flex items-center"
          >
            <Icon name={saved ? 'bookmark_added' : 'bookmark_add'} filled={saved} />
          </button>
        )}
        {/* Padded past the save button so a long title wraps instead of running
            underneath it on a phone. */}
        <h2 className="font-display-lg text-display-lg-mobile md:text-display-lg text-on-background mb-2 px-10">
          {recipe.title || 'Recipe'}
        </h2>
        <MetaRow recipe={recipe} />
      </header>

      {ingredients.length > 0 && (
        <section className="mb-12">
          <h3 className="font-headline-md text-headline-md text-primary mb-6 border-b border-outline-variant pb-2">
            Ingredients
          </h3>
          <ul className="grid md:grid-cols-2 gap-y-3 gap-x-8 font-ui-main text-on-surface">
            {ingredients.map((ingredient, index) => (
              <li key={`${ingredient}-${index}`} className="flex items-start gap-3">
                <span className="text-primary font-bold" aria-hidden="true">
                  •
                </span>
                {ingredient}
              </li>
            ))}
          </ul>
        </section>
      )}

      {steps.length > 0 && (
        <section className="mb-12">
          <h3 className="font-headline-md text-headline-md text-primary mb-6 border-b border-outline-variant pb-2">
            Preparation
          </h3>
          <ol className="space-y-8">
            {steps.map((step, index) => (
              <li key={`${index}-${step.slice(0, 24)}`} className="flex gap-4 md:gap-6">
                <span
                  className="font-display-lg text-display-lg text-primary/20 shrink-0 select-none leading-none"
                  aria-hidden="true"
                >
                  {String(index + 1).padStart(2, '0')}
                </span>
                <p className="font-recipe-body text-recipe-body leading-relaxed pt-2">{step}</p>
              </li>
            ))}
          </ol>
        </section>
      )}

      {/* Fixed app-owned wording, driven by the done event's boolean. The mockup
          shows the model writing this; it must not. */}
      {allergenNotice && <AllergenNotice />}

      {links.length > 0 && <SourceChips sources={links} />}
    </article>
  )
}
