# PantryPal v1 — Scoping

Written before implementation, from the four artifacts in `/brief/`. Where stakeholders conflicted I made a call and recorded it rather than building toward both.

---

## Scope committed

1. **Conversational cooking assistant** covering Priya's three functional asks: general cooking questions, recipe suggestion, and "what can I make with what I have."
2. **LLM-driven tool use** on LangGraph — the model decides when to call tools. Tools: `web_search` (external), `read_profile`, `update_profile`. No hardcoded call sequences.
3. **Persistent user profile across sessions** — cookware, cuisines, tastes, skill level, dislikes, and dietary *preferences*. This is Marcus's headline feature and Jordan confirms it as a top user complaint.
4. **Cookware learned conversationally, starting from empty.** No assumed starter kit, no onboarding form. The assistant asks only when equipment is load-bearing for a suggestion, then remembers the answer.
5. **Feasibility check with substitution.** Before suggesting a recipe, check it against the user's known kit. When it doesn't fit, offer the closest thing they *can* make. Never a bare refusal — Jordan is explicit that flat "you can't make this" reads as failure.
6. **Allergen notice as a structured response field**, rendered by the frontend on any turn that suggests a recipe or ingredient. Not model-authored prose.
7. **Two-tier model routing with streaming** — a small fast model for simple turns, a stronger model for tool-using or multi-constraint turns.
8. **Topic policy:** food-adjacent is in scope (wine, equipment, hosting, technique). Clearly off-topic is politely redirected. Medical and food-safety questions are declined warmly, with an offer of what the assistant *can* help with.
9. **Profile transparency:** the user can view, edit, and delete everything stored about them.
10. **Stack:** FastAPI + LangGraph, all LLM calls through LangChain, chat frontend, Docker Compose.

---

## Scope cut

- **PDF / cookbook ingestion** — Jordan filed this as explicitly not-v1. Document ingestion is its own project and would consume the entire window.
- **Grocery list export** — Jordan marked it v2. It depends on multi-day meal planning, which doesn't exist yet; building the export before the thing it exports from is backwards.
- **Hands-free voice** — Marcus left this to my judgment. Cut for v1, but kept architecturally open: the assistant's reply is a plain-text field separate from UI chrome, so a TTS layer can consume it without restructuring the response.
- **Saved favorites** — raised in every interview, which is real signal, but it's CRUD. It demonstrates none of what this build is being evaluated on, and the profile store makes it a small addition later.
- **Medical and dietary adaptation** — Diane, non-negotiable. Preferences are accommodated; conditions are not.
- **Food safety judgments** — Diane, non-negotiable.
- **Live restaurant/local data** — Marcus counts it as food world, but it needs a places API and location handling for marginal v1 value. Restaurant *discussion* is in scope; live lookup is not.

---

## Contradictions resolved

**Memory vs. data retention — Marcus vs. Diane.** Marcus's strongest ask ("I told it I'm allergic to shellfish, don't suggest shrimp") collides with Diane's preference to store no health-related mentions. Resolved with three tiers: preferences and cookware persist freely; **allergies persist as a behavioral exclusion only** (`never suggest: shellfish`) with no medical reasoning attached to them; medical conditions are never written down — acknowledged generically in-turn, with a pointer to a professional. This delivers Marcus's exact example while storing a filter rule rather than a diagnosis. Flagged to Diane below, because it is the assumption the design rests on.

**Personality vs. disclaimers — Marcus vs. Diane.** Marcus wants opinions and no hedging; Diane requires a visible allergen notice on every recipe or ingredient suggestion. Resolved by separating layers: the assistant's prose stays opinionated, and the notice is a structured field the UI renders as chrome. Diane's stated concern was inconsistency — this makes it consistent by construction, and the model can't dilute it into apologetic prose.

**Latency — Priya vs. Marcus.** Priya wants sub-2s; Marcus won't trade quality for speed. Resolved by routing and streaming: simple turns go to a fast model and finish quickly, hard turns take longer but stream, so time-to-first-token stays under 2s in both cases. This also answers Priya's per-query cost concern with the same mechanism.

**Topic guardrails — Priya vs. Marcus.** Priya wants a strict cooking-only boundary; Marcus wants food-adjacent latitude and explicitly doesn't want a "narc." Marcus wins on breadth, because Priya's underlying goal is that users understand what the product is for, and a warm redirect achieves that better than a refusal. Diane's two categories remain hard limits regardless.

**Food safety — Diane vs. Jordan's users.** Diane forbids spoilage guidance; Jordan's older users ask constantly and won't stop. Not resolvable in the users' favor, so the decline is designed rather than bolted on: acknowledge, point to food safety authorities, and immediately offer something useful in the same breath. Same never-bare-refuse pattern as cookware.

---

## Clarifying questions

1. **Diane:** does an allergy stored as a hard ingredient-exclusion, with no medical reasoning attached, fall under your item 3? The memory design assumes no. If yes, Marcus's headline feature becomes session-scoped and I would rebuild it.
2. **Priya / Marcus:** is 2 seconds a cap on time-to-first-token or full response? Streaming resolves your disagreement if it's the former and does not if it's the latter.
3. **Diane:** does a deletion request purge conversation logs, or only the structured profile? This changes the storage layout, and retrofitting it is expensive.
4. **Jordan:** when the assistant is missing a cookware fact mid-suggestion, does your interview data show users prefer being asked, or assumed-and-caveated? You have the research; I'd rather not guess at the interaction that drives your top churn cause.
5. **Marcus:** "is this restaurant worth going to" needs live web data. In scope for v1, or is search reserved for recipes and technique?

---

## Assumptions made

- **Allergy-as-exclusion is not health data under Diane's item 3.** The single load-bearing assumption in the build.
- **13+ only, gated by terms of service, no age data collected.** Diane asked for a COPPA stance in item 5 and nobody answered her; this is mine.
- **Recipes are model-generated and search-augmented**, not drawn from a licensed corpus. No rights or accuracy guarantees on recipe content.
- **Identity is a client-supplied user ID with no authentication.** Sufficient to demonstrate persistence; not a production posture.
- **"Under 2 seconds" refers to perceived responsiveness**, which streaming satisfies.
- **The cold-start profile is empty rather than assumed.** Early conversations will be less capable in exchange for never being confidently wrong about the user's kitchen — Jordan's data says the second failure is far more expensive.

---

## Risks accepted

- **Allergen exclusion is ingredient-name matching and will miss derived ingredients** — anchovy in Worcestershire sauce, shellfish in some stocks. A real gap on the highest-stakes path. Accepted for v1 and surfaced by the standing allergen notice; the right fix is an ingredient taxonomy, which is out of window.
- **The topic boundary is model-judged, not deterministic.** The brief promises adversarial testing. Some inputs will get through the policy layer; I have chosen a warm, generous boundary over a brittle strict one, which raises this risk deliberately.
- **Sparse early profiles.** Learning cookware conversationally means the first sessions know little, and the feasibility check is only as good as what's been learned.
- **Routing misclassification.** A hard query routed to the fast model produces a worse answer than a single strong model would. Cost and latency are bought with occasional quality variance.
- **No authentication on profile data**, including allergy exclusions. Acceptable for a demo, not for anything real.
- **Diane's items 3 and 5 are unresolved with counsel.** I built to my reading of them; both could force rework.
