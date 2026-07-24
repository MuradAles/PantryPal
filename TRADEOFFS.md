# Trade-offs

What actually got built, what it cost, and what is still wrong with it. `SCOPING.md` holds the decisions made before writing code; this is the account of what survived contact with the work.

---

## Built vs scoped

Everything in `SCOPING.md`'s committed scope shipped. Two items shipped weaker than written, and one legal requirement grew during the build.

**Weaker than scoped:**

- **Feasibility checking is instructed, not enforced.** The scope said the assistant never suggests a recipe the user cannot make. In practice the profile is injected into the system prompt and the model is told to cook inside the user's kitchen. There is no code that inspects a suggestion and rejects it for requiring an oven. It behaves correctly in testing, but it is a prompt-level guarantee, not a structural one — unlike the medical write guard, which is structural. Given more time this is the first thing I would harden.

- **The allergen notice shows on every substantive reply**, not only on recipe suggestions. This is a deliberate widening, explained below.

**Grew during the build:**

- **Deletion had to cover conversation history, not just the profile.** Once the LangGraph checkpointer landed, `DELETE /api/profile` was wiping stored facts while leaving a verbatim transcript keyed by the same user id. That transcript can contain the health mentions the write guard specifically refuses to store as facts — so the guard was defeatable through the back door. Both are now deleted together. This was not in the original scope and should have been.

---

## Trade-offs

**SQLite instead of Postgres.** A file on a volume rather than a second container and a startup race. `db.py` is the only module that touches storage, so moving to Postgres later is one file. The cost is real: SQLite has no array type, so list columns are JSON text encoded at that boundary, and concurrent writes needed an explicit `BEGIN IMMEDIATE` transaction that Postgres would have handled more naturally.

**A keyword layer in front of the LLM classifier.** Food-safety and medical phrasings are matched by regex before any model is called. This costs a maintained pattern list and some false positives, and buys three things: blocked messages cost zero API calls, the block cannot be argued out of by instruction-shaped text in the message, and a classifier outage degrades to "less nuanced" rather than "no legal protection". Prompt injection is tested directly against this layer.

**The allergen notice is always on.** Counsel requires it on any response naming a recipe or ingredient. I first wrote a heuristic that looked for measurements, cooking verbs and common ingredients — and it missed "Smash burgers. Thin patties, screaming hot pan," an unambiguous recipe suggestion. A heuristic that fails on a case that plain is not fit to gate a legal requirement, so it now fires on every substantive reply and only declines are exempt. The risk is asymmetric: a notice shown unnecessarily is a line of UI chrome, a notice missed once is the thing counsel wrote the email about. The heuristic survives as `looks_like_a_recipe()` for the frontend to soften presentation, never to decide appearance.

**Allergies are stored as bare ingredient names.** "I'm allergic to shellfish" becomes `avoid: ["shellfish"]` with no record of why. This delivers the CEO's own example — told once, never suggested again — while storing a filter rule rather than a diagnosis. It is the narrowest reading that satisfies both him and counsel, and it is the single assumption the memory design rests on. If counsel disagrees, memory becomes session-scoped and the feature largely dies.

**Model routing inside one model family.** Every Pro tier is quota-zero on a free AI Studio key, verified against the live API. Rather than drop routing — which is a stated product requirement about per-query cost — the tiers use two flash-lite models with a real capability gap. So the smart tier is the stronger available small model, not a genuinely larger one.

**The frontend is deliberately unstyled.** Product asked for something simple they would rebuild anyway. Components use semantic class names so a visual design lands as CSS alone, with no changes to the code that carries the allergen-notice guarantee or the SSE parsing.

**No authentication.** `user_id` is client-supplied from localStorage. Enough to demonstrate persistence, nowhere near enough for production — anyone who guesses an id can read that profile. The model itself cannot: `user_id` travels in the run config, never in tool arguments, so it cannot reach another user's data by inventing one.

---

## Known issues

**The keyword policy layer is English-only.** A food-safety question in Russian or Japanese falls through to the LLM classifier, which handles it correctly while it is up. But `classify()` fails open on error, so during a classifier outage a non-English user loses the deterministic backstop an English user keeps. The failure is silent and only affects some users, which is the worst shape for a gap like this.

**Allergen exclusion is ingredient-name matching.** `avoid: ["shellfish"]` will not catch anchovy in Worcestershire sauce or shellfish in a stock. This is a real gap on the highest-stakes path, mitigated only by the standing allergen notice. The correct fix is an ingredient taxonomy, which was out of window.

**Feasibility checking is prompt-level.** See above. A model that ignores its instructions can suggest something the user cannot cook.

**Free tier is 20 requests per day, per model id.** Not per project — a fact that cost real time to learn. One chat turn costs several calls (classifier, plus one per agent loop iteration), so roughly five to eight conversations per model before exhaustion. `gemini-2.5-flash` was exhausted during development; the flash-lite ids carry their own budgets. A reviewer using their own key will not hit this.

**`docker compose restart` does not pick up `.env` changes.** `env_file` is baked at container creation, so an edited `.env` needs `up -d --force-recreate`. This produced a confusing failure where the container ran model ids that no longer existed anywhere in the repo. Documented in the README because a cloner will hit it.

**The sources strip has never rendered from a real search.** Its contract is covered by tests and it renders correctly from a stub, but no live reply has yet included web results, so that path is unproven end to end.

**Routing depends on the classifier's difficulty judgement.** A hard question misrouted to the fast tier produces a worse answer than a single stronger model would. Cost and latency are bought with occasional quality variance.

**The topic boundary is model-judged beyond the keyword layer.** The brief promises adversarial testing. A generous boundary was chosen over a brittle one, which raises this risk deliberately.

---

## What I would do next

**Harden the feasibility check.** Move it from instruction to structure: have the model return the equipment a suggestion requires, and reject or substitute in code when it is not in the profile. This is the gap between "behaves correctly in testing" and "cannot behave incorrectly", and it is the same difference that makes the medical write guard trustworthy.

**An ingredient taxonomy for allergens.** Derived ingredients are the real failure mode, and name matching cannot reach them.

**A multilingual policy layer.** Either translate before classifying, or accept non-English messages only while the classifier is healthy and say so.

**Wire the backup model as a LangChain fallback.** `MODEL_BACKUP` is configured but unused. Because daily caps are per model id, a primary running dry currently takes the whole product down instead of degrading. The wrinkle is that `RunnableWithFallbacks` has no `bind_tools`, so tools must be bound to each model before composing.

**Then the deferred scope**, in the order the CX interviews justify: saved favourites, grocery list export, and only then cookbook ingestion.

---

## A note on verification

168 tests pass and cost no API quota — every model in the suite is scripted locally. That is the right default, and it is also how a real bug survived a fully green suite: the model was not calling `remember_about_user` at all, because the persona told it to save things "quietly", which a small model read as low priority. Scripted models call whatever the script says, so no mocked test could have caught it. One real request did.

What has been verified against the live API: streaming, the allergen notice rendering on a genuine 1170-character recipe as an element outside the prose, the model saving cookware unprompted and the panel picking it up, blocked topics returning declines without reaching a model, and the profile routes.

What has not: sources from a real search, and long-run behaviour of anything.
