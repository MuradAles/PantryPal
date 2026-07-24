# PantryPal v1: Scoping

Written before implementation, from the four artifacts in `/brief/`. Where stakeholders conflicted I made a call and recorded it rather than building toward both.

Reread against the finished build and corrected where it had drifted. Seven things changed once code met the brief, and the last section of this document lists every one of them with what it originally said. I would rather a reader see a decision get reversed than read a scoping doc that quietly agrees with whatever shipped.

---

## Scope committed

1. Conversational cooking assistant covering Priya's three functional asks: general cooking questions, recipe suggestion, and "what can I make with what I have."
2. LLM-driven tool use on LangGraph. The model decides when to call tools. The tools are `search_web` (external), `get_user_profile`, `remember_about_user`, and `present_recipe`. No hardcoded call sequences.
3. Persistent user profile across sessions: cookware, cuisines, tastes, skill level, dislikes, dietary preferences. This is Marcus's headline feature, and Jordan confirms it as a top user complaint.
4. Cookware learned conversationally, starting from empty. No assumed starter kit, no onboarding form. The assistant asks only when equipment is load-bearing for a suggestion, then remembers the answer.
5. Feasibility check with substitution. Before suggesting a recipe, check it against the user's known kit. When it does not fit, offer the closest thing they can make. Jordan is explicit that a flat "you can't make this" reads as failure.
6. Allergen notice as a structured response field, rendered by the frontend on every substantive reply. Not model-authored prose. This started as "any turn that suggests a recipe or ingredient" and was widened during the build, for reasons in `TRADEOFFS.md`.
7. Two-tier model routing with streaming. A small fast model for simple turns, a stronger one for tool-using or multi-constraint turns. Both tiers ended up inside the flash-lite family, because every Pro tier is quota-zero on a free key.
8. Topic policy. Food-adjacent is in scope, covering wine, equipment, hosting, technique. Clearly off-topic gets a polite redirect. Medical and food-safety questions are declined warmly, with an offer of what the assistant can help with instead.
9. Profile transparency. The user can view, edit, and delete everything stored about them. Deletion covers the structured profile, the conversation thread, and saved recipes together.
10. Stack: FastAPI with LangGraph, all LLM calls through LangChain, a chat frontend, Docker Compose.
11. Saved recipes. A recipe the assistant presents can be kept and read back later. This was in the cut list when this document was written, and the reversal is explained below.

---

## Scope cut

**PDF and cookbook ingestion.** Jordan filed this as explicitly not-v1. Document ingestion is its own project and would consume the entire window.

**Grocery list export.** Jordan marked it v2. It depends on multi-day meal planning, which does not exist yet, and building the export before the thing it exports from is backwards.

**Hands-free voice.** Marcus left this to my judgment. Cut for v1, but kept architecturally open: the assistant's reply is a plain-text field separate from UI chrome, so a text-to-speech layer can consume it later without restructuring the response.

**Saved favourites. Cut here, then reversed and built.** The original reasoning, kept because it is the part worth arguing with: raised in every interview, which is real signal, but it is CRUD, it demonstrates none of what this build is being evaluated on, and the profile store makes it a small addition later. That was wrong about the second clause. Reversed mid-build and shipped as item 11 in committed scope. `TRADEOFFS.md` has the argument that changed my mind.

**Medical and dietary adaptation.** Counsel, non-negotiable. Preferences are accommodated. Conditions are not.

**Food safety judgments.** Counsel, non-negotiable.

**Live restaurant and local data.** Marcus counts it as food world, but it needs a places API and location handling for marginal v1 value. Restaurant discussion is in scope. Live lookup is not.

---

## Contradictions resolved

**Memory versus data retention. Marcus against Diane.** Marcus's strongest ask, "I told it I'm allergic to shellfish, don't suggest shrimp," collides with Diane's preference to store no health-related mentions. Resolved with three tiers. Preferences and cookware persist normally. Allergies persist as a behavioural exclusion only, written as `never suggest: shellfish` with no medical reasoning attached to it. Medical conditions are never written down at all, only acknowledged in the turn with a pointer to a professional. That delivers Marcus's exact example while storing a filter rule rather than a diagnosis. Flagged to Diane below, because it is the assumption the design rests on.

**Personality versus disclaimers. Marcus against Diane.** Marcus wants opinions and no hedging. Diane requires a visible allergen notice on every recipe or ingredient suggestion. Resolved by separating the layers: the assistant's prose stays opinionated, and the notice is a structured field the UI renders as chrome. Diane's stated concern was inconsistency, so this makes it consistent by construction, and the model cannot dilute it into apologetic prose.

**Latency. Priya against Marcus.** Priya wants sub-2-second responses. Marcus will not trade quality for speed. Resolved by routing and streaming. Simple turns go to a fast model and finish quickly. Hard turns take longer but stream, so time-to-first-token stays under two seconds either way. The same mechanism also answers Priya's per-query cost concern.

**Topic guardrails. Priya against Marcus.** Priya wants a strict cooking-only boundary. Marcus wants food-adjacent latitude and explicitly does not want a "narc." Marcus wins on breadth, because Priya's underlying goal is that users understand what the product is for, and a warm redirect achieves that better than a refusal does. Diane's two categories remain hard limits regardless.

**Food safety. Diane against Jordan's users.** Diane forbids spoilage guidance. Jordan's older users ask constantly and will not stop. This is not resolvable in the users' favour, so the decline is designed rather than bolted on: acknowledge, point to food safety authorities, then immediately offer something useful in the same breath. Same never-bare-refuse pattern as the cookware case.

---

## Clarifying questions

1. **Diane:** does an allergy stored as a hard ingredient exclusion, with no medical reasoning attached, fall under your item 3? The memory design assumes it does not. If it does, Marcus's headline feature becomes session-scoped and I would rebuild it.
2. **Priya and Marcus:** is two seconds a cap on time-to-first-token, or on the full response? Streaming resolves your disagreement if it is the former. It does not if it is the latter.
3. **Diane:** does a deletion request purge conversation logs, or only the structured profile? This changes the storage layout, and retrofitting it is expensive.
4. **Jordan:** when the assistant is missing a cookware fact mid-suggestion, does your interview data show users prefer being asked, or assumed-and-caveated? You have the research, and I would rather not guess at the interaction driving your top churn cause.
5. **Marcus:** "is this restaurant worth going to" needs live web data. Is that in scope for v1, or is search reserved for recipes and technique?

---

## Assumptions made

**Allergy-as-exclusion is not health data under Diane's item 3.** The single load-bearing assumption in the build.

**Users are 13 or older, gated by terms of service, with no age data collected.** Diane asked for a COPPA stance in item 5 and nobody answered her. This is mine.

**Recipes are model-generated and search-augmented**, not drawn from a licensed corpus. No rights or accuracy guarantees on recipe content.

**Identity is a client-supplied user ID with no authentication.** Enough to demonstrate persistence. Not a production posture.

**"Under two seconds" refers to perceived responsiveness**, which streaming satisfies.

**The cold-start profile is empty rather than assumed.** Early conversations will be less capable, in exchange for never being confidently wrong about the user's kitchen. Jordan's data says the second failure costs far more.

---

## Risks accepted

**Allergen exclusion is ingredient-name matching, so it will miss derived ingredients.** Anchovy in Worcestershire sauce, shellfish in some stocks. A real gap on the highest-stakes path. Accepted for v1 and surfaced by the standing allergen notice. The right fix is an ingredient taxonomy, which is out of window.

**The topic boundary is model-judged rather than deterministic.** The brief promises adversarial testing, so some inputs will get through the policy layer. I have chosen a warm, generous boundary over a brittle strict one, which raises this risk deliberately.

**Sparse early profiles.** Learning cookware conversationally means the first sessions know little, and the feasibility check is only as good as what has been learned so far.

**Routing misclassification.** A hard query routed to the fast model produces a worse answer than a single strong model would. Cost and latency are bought with occasional quality variance.

**No authentication on profile data**, including allergy exclusions. Acceptable for a demo, not for anything real.

**Diane's items 3 and 5 are unresolved with counsel.** I built to my reading of them. Either could force rework.

---

## Where this document drifted

Seven corrections, made after the build and listed with what the original text said. Each one is a place where writing the code taught me something the planning did not.

**Saved recipes moved from cut to built.** Originally cut as "it is CRUD, it demonstrates none of what this build is being evaluated on." The first clause holds. The second was wrong, and I reversed it mid-build. The argument is in `TRADEOFFS.md`.

**The allergen notice fires on every substantive reply, not only on recipe turns.** Item 6 originally read "on any turn that suggests a recipe or ingredient." I built that as a heuristic, watched it miss an obvious recipe suggestion, and widened the rule rather than keep tuning a detector that was gating a legal requirement.

**Both routing tiers are flash-lite.** Item 7 promised "a small fast model for simple turns, a stronger one" for hard ones. Every Gemini Pro tier turned out to be quota-zero on a free AI Studio key. The routing mechanism is real and the tiers are genuinely different model ids, but the capability gap between them is much smaller than this document implies.

**Deletion grew past the profile.** Item 9 originally covered "everything stored about them," which at planning time meant the profile row. Once conversations persisted, a verbatim transcript keyed to the same user survived a deletion, and later saved recipes did too. All three are now erased together.

**There are four tools, not three, and none of my three had the name I gave it.** Item 2 listed `web_search`, `read_profile` and `update_profile`. What shipped is `search_web`, `get_user_profile`, `remember_about_user`, and a fourth, `present_recipe`, which arrived with structured recipes.

**The feasibility check is instructed, not enforced.** Item 5 says the assistant checks a recipe against the user's kit before suggesting it. In the shipped system the profile goes into the system prompt and the model is told to cook inside that kitchen. No code inspects a suggestion and rejects it. This is the largest gap between what this document promised and what runs, and it is the first thing I would fix.

**Clarifying question 3 got answered by the build rather than by Diane.** I asked whether a deletion request purges conversation logs or only the structured profile, and noted that retrofitting it would be expensive. Nobody answered, the checkpointer landed, and the answer became obvious the moment a stored transcript could contain the health mentions the write guard refuses to store as facts. It was cheaper to retrofit than I predicted, which is the one thing on this list I got wrong in my own favour.
