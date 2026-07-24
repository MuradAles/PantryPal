# Trade-offs

What actually got built, what it cost, and what is still wrong with it. `SCOPING.md` holds the decisions made before any code was written. This is the account of what survived contact with the work.

---

## Built versus scoped

Everything in `SCOPING.md`'s committed scope shipped. Two items shipped weaker than written, one legal requirement grew during the build, and one thing I had explicitly cut got built anyway.

### Weaker than scoped

**Feasibility checking is instructed, not enforced.** The scope said the assistant never suggests a recipe the user cannot make. In practice the profile is injected into the system prompt and the model is told to cook inside the user's kitchen. There is no code that inspects a suggestion and rejects it for requiring an oven. It behaves correctly in testing, but it is a prompt-level guarantee rather than a structural one, unlike the medical write guard. Given more time this is the first thing I would harden.

**The allergen notice shows on every substantive reply**, not only on recipe suggestions. That is a deliberate widening, explained below.

### Grew during the build

**Deletion had to cover conversation history, not just the profile.** Once the LangGraph checkpointer landed, `DELETE /api/profile` was wiping stored facts while leaving a verbatim transcript keyed by the same user id. That transcript can contain the health mentions the write guard specifically refuses to store as facts, so the guard was defeatable through the back door. Both are now deleted together. This was not in the original scope, and it should have been. Saved recipes became a third store on the same route later, for the same reason.

### Reversed during the build

**Saved recipes were cut, then built.** `SCOPING.md` put favourites in the cut list on the argument that they are CRUD and demonstrate none of what this build is being evaluated on. I still think the first half of that is true. Saving a row is not interesting work.

What changed my mind was structured recipe output landing first. Once the model has a `present_recipe` tool and a recipe exists as an object with a title, steps and ingredients rather than as a paragraph of prose, keeping one stops being a bolt-on and starts being the thing that proves the structured output is real. A card you can save, reopen and delete is evidence the shape is stable. A card that only ever renders once and scrolls away is not.

It also bought a second test of the deletion requirement. `DELETE /api/profile` now has to erase three stores rather than one, and getting that right across stores that cannot share a transaction is a harder problem than the original single-table delete. Counsel's requirement got a sterner exercise than it would have otherwise.

The honest version is that I cut it for a good reason and reversed on a better one, and the cost was real: it is time that did not go into hardening the feasibility check, which is still the weakest guarantee in the build.

---

## Trade-offs

**SQLite instead of Postgres.** A file on a volume rather than a second container and a startup race. `db.py` is the only module that touches storage, so moving to Postgres later is one file. The cost is real. SQLite has no array type, so list columns are JSON text encoded at that boundary, and concurrent writes needed an explicit `BEGIN IMMEDIATE` transaction that Postgres would have handled more naturally.

**A keyword layer in front of the LLM classifier.** Food-safety and medical phrasings are matched by regex before any model is called. This costs a pattern list somebody has to maintain, plus some false positives. It buys three things. Blocked messages cost zero API calls. The block cannot be argued out of by instruction-shaped text in the message. And a classifier outage degrades to "less nuanced" rather than "no legal protection." Prompt injection is tested directly against this layer.

**The allergen notice is always on.** Counsel requires it on any response naming a recipe or ingredient. I first wrote a heuristic looking for measurements, cooking verbs and common ingredients, and it missed "Smash burgers. Thin patties, screaming hot pan," which is an unambiguous recipe suggestion. A heuristic that fails on a case that plain is not fit to gate a legal requirement. It now fires on every substantive reply, and only declines are exempt. The risk is asymmetric: a notice shown unnecessarily is a line of UI chrome, while a notice missed once is the thing counsel wrote the email about. The heuristic survives as `looks_like_a_recipe()` for the frontend to soften presentation, never to decide appearance.

**Allergies are stored as bare ingredient names.** "I'm allergic to shellfish" becomes `avoid: ["shellfish"]` with no record of why. This delivers the CEO's own example, told once and never suggested again, while storing a filter rule rather than a diagnosis. It is the narrowest reading that satisfies both him and counsel, and it is the single assumption the memory design rests on. If counsel disagrees, memory becomes session-scoped and the feature largely dies.

**Model routing inside one model family.** Every Pro tier is quota-zero on a free AI Studio key, which I verified against the live API. Rather than drop routing, which is a stated product requirement about per-query cost, the tiers stayed inside flash-lite: `gemini-3.1-flash-lite` for the fast tier and `gemini-3.5-flash-lite` for the smart one. The routing mechanism is real and the two tiers are genuinely different model ids, but I have not measured the quality difference between them, so I will not claim a capability gap I cannot show you. Treat this as routing that is wired correctly and waiting for a model worth routing to.

The classifier sits on the same id as the fast tier, so they share one daily allowance instead of having one each. That was not the intent. Free-tier caps are per model id, and the whole reason for naming the classifier separately in config was to give it its own budget. `.env.example` now says this plainly rather than describing the split it was supposed to have. The real fix is a different model id, which needs a live call to confirm the candidate resolves, and that call was not available.

**The frontend was built unstyled first, then styled.** Product asked for something simple they would rebuild anyway, so the first version was structure only, with semantic class names chosen so a visual design could land without touching the code carrying the allergen-notice guarantee or the SSE parsing. A design arrived later and that bet paid: the styling pass changed presentation and left both of those alone.

Two deliberate departures from the design file. The recipe step numerals were sized up, because the mockup's class set family without size and renders them at body size, which is plainly not what the design intends. And the responsive breakpoints were moved so that both side rails collapse at the same width, because as drawn there is a range of window sizes with no route to the profile panel, and the delete-everything control lives in that panel. A legal requirement being unreachable between 768 and 1280 pixels is not a design decision I was willing to ship.

There are no frontend tests. Verification was manual browser runs against the real backend with the chat endpoint stubbed. That is the largest untested surface in the build after the live model behaviour.

**No authentication.** `user_id` is client-supplied from localStorage. Enough to demonstrate persistence, nowhere near enough for production, since anyone who guesses an id can read that profile and write to that recipe list. The model itself cannot: `user_id` travels in the run config rather than in tool arguments, so it cannot reach another user's data by inventing one. Ownership is at least enforced consistently within that limit. The saved-recipe delete puts `user_id` in the `WHERE` clause rather than checking it after the fact, so one user cannot delete another's recipe even by id.

---

## Known issues

**The keyword policy layer is English-only.** `FOOD_SAFETY_PATTERNS` and `MEDICAL_TERMS` are English regexes, so `keyword_topic()` returns None for a food-safety question asked in Russian, Spanish or Japanese. Those messages fall through to the LLM classifier, which does understand them, so the legal guarantee holds in normal operation. Ordinary non-English conversation works fine end to end, and there are tests covering Russian, Spanish, Japanese and an emoji-only message.

What a non-English speaker loses is the deterministic backstop. `classify()` fails open to OK on error, so during a classifier outage an English user is still protected by the keyword pass and a non-English user is not. The failure is silent and affects only some users, which is the worst shape a gap like this can take.

It shipped that way because translating a denylist into n languages is a maintenance surface with no obvious stopping point, and every language added is a fresh source of false positives that block ordinary cooking questions. One deterministic language plus a multilingual classifier was the v1 answer. The better fix is cheap: detect the language ahead of the keyword layer, route anything non-English straight to the classifier, and have that path fail closed rather than open.

**Allergen exclusion is ingredient-name matching.** `avoid: ["shellfish"]` will not catch anchovy in Worcestershire sauce, or shellfish in a stock. A real gap on the highest-stakes path, mitigated only by the standing allergen notice. The correct fix is an ingredient taxonomy, which was out of window.

**The medical write guard is a denylist, and a denylist has a coverage limit.** This is the part of the build I point at as structural rather than instructed, so it deserves the caveat stated plainly. `MEDICAL_TERMS` is a finite list of about forty patterns. It catches "diabetes" and "pregnant". It does not catch "lactose intolerant", "acid reflux", "on warfarin" or "no gallbladder", and if the model calls `remember_about_user` with one of those the phrase reaches SQLite verbatim.

Two things narrow the exposure without closing it. Most of these phrasings classify as MEDICAL at the policy layer and never reach the agent, so the model is rarely in a position to try. And the schema has no medical column, so what lands is a stray string in `dislikes` rather than a health record in a field designed to hold one. Neither is the guarantee the list is supposed to provide.

Widening the list is the obvious patch and it is genuinely delicate, because "gluten" and "lactose" have to stay storable as bare ingredient names. That is the whole memory design: an allergy persists as an ingredient to avoid, not as a diagnosis. A denylist that swallows the ingredient along with the condition breaks the feature it exists to protect. The real fix is to classify the phrase before storing it rather than pattern-match it, which is a model call on the write path and was out of window.

**Feasibility checking is prompt-level.** See above. A model that ignores its instructions can suggest something the user cannot cook.

**The model fallback fires on any error, not just on quota.** It is composed with LangChain's default handling, which catches a bare `Exception`. A malformed request now gets retried once against the backup and fails again, more slowly. Narrowing it to the provider's quota exception needs a live call to learn the exact type, and that call was not available. It has also never been exercised against a real 429.

**Free tier is 20 requests per day, per model id.** Not per project, which is a fact that cost real time to learn. One chat turn costs several calls, one for the classifier plus one per agent loop iteration, so roughly five to eight conversations per model before exhaustion. `gemini-2.5-flash` was exhausted during development. The flash-lite ids carry their own budgets. A reviewer using their own key will not hit this.

**`docker compose restart` does not pick up `.env` changes.** `env_file` is baked at container creation, so an edited `.env` needs `up -d --force-recreate`. This produced a confusing failure where the container was running model ids that no longer existed anywhere in the repo. It is documented in the README, because a cloner will hit it too.

**The sources strip has never rendered from a real search.** Its contract is covered by tests and it renders correctly from a stub, but no live reply has yet included web results, so that path is unproven end to end.

**`present_recipe` now competes with `search_web` for the same tool budget.** The agent loop is still capped at 5 iterations. A turn that searches twice and then presents a card fits, but the ceiling was set when there were three tools and it has not been revisited with four. A turn that needed several searches before it had a recipe worth showing could hit the cap and lose the card.

**The saved-recipe cap is not covered by the suite.** Storage keeps the newest 200 recipes per user and trims older ones. I checked that by hand with a throwaway script at a stand-in cap of three, and it behaved, but there is no permanent test. A test that writes 201 rows to assert one gets dropped costs more than it protects, so I left it out deliberately rather than by oversight.

**Routing depends on the classifier's difficulty judgment.** A hard question misrouted to the fast tier produces a worse answer than a single stronger model would. Cost and latency are bought with occasional quality variance.

**The topic boundary is model-judged beyond the keyword layer.** The brief promises adversarial testing. A generous boundary was chosen over a brittle one, which raises this risk deliberately.

---

## What I would do next

**Harden the feasibility check.** Move it from instruction to structure: have the model return the equipment a suggestion requires, then reject or substitute in code when that equipment is not in the profile. This is the gap between "behaves correctly in testing" and "cannot behave incorrectly." The medical write guard sits on the right side of that line structurally, in that it is on the only write path and cannot be talked out of, even though its denylist has the coverage limit described above. The feasibility check is not on that side of the line at all.

**An ingredient taxonomy for allergens.** Derived ingredients are the real failure mode, and name matching cannot reach them.

**A multilingual policy layer.** Either translate before classifying, or accept non-English messages only while the classifier is healthy and say so plainly.

**Point `MODEL_BACKUP` at a model id nothing else uses.** The fallback itself is now built. The agent, the finalize step and the classifier all run through a primary with the backup composed underneath, and tools are bound to both models before the fallback is composed, because `RunnableWithFallbacks` has no `bind_tools`. The fallback is deliberately skipped when the backup resolves to the same id as the primary, since daily caps are per model id and falling back to an exhausted allowance just buys a slower identical 429.

That skip is doing more work than it should. Under the shipped `.env`, `MODEL_BACKUP` is the same id as `MODEL_FAST`, so the tier carrying nearly every turn is the one tier with no armed fallback. The mechanism is right and the values are wrong, which is a one-line config change gated on confirming a candidate model id actually resolves.

**Then the deferred scope**, in the order the CX interviews justify. Saved recipes came forward and shipped, so what is left is grocery list export, and only after that cookbook ingestion.

---

## A note on verification

212 tests pass in under two seconds and cost no API quota, because every model in the suite is scripted locally. That is the right default. It is also how two real bugs survived a fully green suite, which is the part of this build I have thought about most.

The first: the model was not calling `remember_about_user` at all. The persona told it to save things "quietly," which a small model read as low priority. Scripted models call whatever the script tells them to, so no mocked test could have caught it. One real request did.

The second is worse, because it was our own doing. A mutation test left `return True  # MUTANT` behind in `delete_profile`. With that line in place the function reported success even when the delete threw, so `DELETE /api/profile` answered 204 on an erase that had not happened. That is counsel's requirement, reporting a deletion that did not occur, and the suite was green over it for several commits. The test that should have caught it called `delete_profile` against a dead database and only asserted that it did not raise. It now asserts the return value is False.

Both failures have the same shape. A test that checks the code was reached is not a test that checks the code was right, and a scripted model tells you what your parser does rather than what the real one will do. The suite is fast and cheap and I would build it the same way again, but I would not read a green run as evidence the thing works.

Verified against the live API: streaming, the allergen notice rendering on a genuine 1170-character recipe as an element outside the prose, the model saving cookware unprompted with the panel picking it up, blocked topics returning declines without reaching a model, and the profile routes.

Verified over real HTTP against the running container, with no model involved: the saved-recipe routes, including a user failing to delete another user's recipe, a stale id answering 404, and `DELETE /api/profile` clearing one user's recipes while leaving another's alone.

Not verified: sources from a real search, whether the model chooses to call `present_recipe` at a sensible rate, and the long-run behaviour of anything. The `present_recipe` gap is the biggest one. The tool docstring and the persona are the only two levers on it, and neither has been watched working against a real model.

---

## Findings from an independent review, and what was done about them

A read-only reviewer audited the committed code near the end of the build. Some of what it found is already described above, so this is the part that is new, plus what was done in response.

**Fixed: the delete route reported success on a failed write.** This is the second bug in the verification note. What the review added is how it got in: the commit carrying it was checked by running the tests rather than by reading the diff, and the mutation's whole purpose had been to prove nothing covered that line. There is now a test that makes the database raise and asserts a 503, so the route cannot quietly answer 204 again.

**Fixed: one click on Stop defeated the allergen notice.** The notice arrives on the final stream frame, and an aborted stream never sends one, so a half-written recipe rendered with no disclosure at all. This is a good illustration of why the notice being server-computed was not by itself enough: the value was right and never reached the screen. The client now applies the notice when a stream ends early with text already on screen, matching the asymmetry the server uses.

**Known and not fixed: an allergy is sometimes filed as a dislike rather than an avoid.** Both are respected in the prompt, so the assistant will not suggest either, but the distinction that matters to counsel is not reliably preserved, because the write path takes whichever field the model chose. This is the same weakness as the denylist above seen from the other side. The guard controls what cannot be written and not which field a legitimate write lands in.

**Known and not fixed: a cold-start race in the graph builder.** Concurrent first requests can each open a checkpointer connection, and all but one are leaked. It only happens on the first requests after a restart, and it leaks connections rather than corrupting data, so it lost to the two fixes above on time.
