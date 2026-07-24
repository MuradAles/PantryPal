# PantryPal v1: Build Spec

Internal working document, kept in `docs/` as a record of how this was built. Companion to `SCOPING.md`, which holds the reasoning behind these decisions.

This was written before the code. Where the build later diverged, the sections below have been corrected, and `SCOPING.md` carries the full list of what changed and why under "Where this document drifted."

---

## 1. Product

A conversational cooking assistant. One chat page. It answers cooking questions, suggests recipes, works out what you can cook from what you have, and remembers you between sessions.

What separates it from a generic chatbot, per the brief:

- It learns your kitchen instead of assuming one, and never suggests a recipe you can't physically make
- When it can't suggest something, it offers an alternative rather than refusing flat
- It has opinions and doesn't hedge
- It obeys three hard legal limits without exception

## 2. Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.12, FastAPI | 3.12 in Docker; local 3.14 is too new for the dependency tree |
| Agent | LangGraph | required |
| LLM access | LangChain + `langchain-google-genai` | required path, no vendor SDK |
| Models | Gemini fast tier / smart tier | routed by difficulty. Both ended up flash-lite, since Pro is quota-zero on a free key |
| Search | Tavily | env var is `TRAVILY_API_KEY` in `.env`; map it in config |
| Database | SQLite | file on a Docker volume; no service to provision |
| Frontend | React + Vite | visual design supplied separately |
| Packaging | Docker Compose | backend now, frontend added in phase 7 |

### Dependencies

Backend:
```
fastapi                        uvicorn[standard]
langgraph                      langchain-core
langchain-google-genai         langgraph-checkpoint-sqlite
langchain-tavily               aiosqlite
pydantic-settings              sse-starlette
pytest  pytest-asyncio  httpx  (dev)
```

Frontend: `react`, `react-dom`, `vite`, `react-markdown`. SSE over native `EventSource`.

## 3. Architecture

```
POST /api/chat
   │
   ▼
classify(message)              one Flash call, returns both:
   ├─ topic: OK | MEDICAL | FOOD_SAFETY | OFF_TOPIC
   └─ difficulty: SIMPLE | HARD
   │
   ├─ topic != OK ──► canned safe response ──► stream ──► END
   │
   ▼
select model   SIMPLE → fast tier   HARD → smart tier
   │
   ▼
LangGraph agent node, tools bound, loops (max 5 iterations)
   ├─ search_web(query)
   ├─ get_user_profile()
   ├─ remember_about_user(cookware?, likes?, dislikes?, avoid?)
   └─ present_recipe(title, steps, ingredients, time_mins?, difficulty?, serves?)
   │
   ▼
attach allergen_notice flag, and the recipe card if one was presented
   │
   ▼
stream tokens (SSE)
```

The model chooses its own tool calls. There is no fixed call order anywhere in the graph. This is an explicit README requirement.

## 4. Data

**`profiles`**

| column | type | notes |
|---|---|---|
| user_id | TEXT PK | client-supplied, localStorage |
| cookware | TEXT (JSON array) | what they own |
| likes | TEXT (JSON array) | cuisines, flavors |
| dislikes | TEXT (JSON array) | won't eat |
| avoid | TEXT (JSON array) | allergen exclusions, stored as ingredient names only |
| updated_at | TEXT | ISO timestamp |

**`saved_recipes`**

| column | type | notes |
|---|---|---|
| id | INTEGER PK | autoincrement, what the delete route takes |
| user_id | TEXT | indexed, and in the WHERE clause of every read and delete |
| title | TEXT | required |
| steps / ingredients | TEXT (JSON array) | same encoding boundary as the profile lists |
| time_mins, difficulty, serves | nullable | a blank slot is honest, an invented forty-five minutes is not |
| saved_at | TEXT | ISO 8601 UTC, because `new Date()` on SQLite's own format is unreliable |

**Conversation state.** A LangGraph SQLite checkpointer, keyed by thread id. Trim to the last 10 turns before sending to the model.

SQLite has no array type, so the list columns are stored as JSON text and encoded at the `db.py` boundary. The access layer is thin on purpose: moving to Postgres later rewrites that one file.

**No medical column exists.** This is deliberate and structural, not a convention.

## 5. The rules

### 5.1 Profile tiers

| Tier | Example | Behavior |
|---|---|---|
| Store freely | "I love Thai food", "I'm vegetarian", "I have an air fryer" | persisted normally |
| Store as a rule | "I'm allergic to shellfish" | written to `avoid` as `shellfish`, with no medical reasoning attached |
| Never store | "I have diabetes", "I'm pregnant" | acknowledged in the reply, pointed to a professional, **not persisted** |

### 5.2 Write guard

`remember_about_user` is model-driven, so the model *will* eventually try to write a medical condition. The prompt is not the defense. The write path is:

```python
def save_profile(user_id, **fields):
    # strip anything matching MEDICAL_TERMS before it reaches SQL
    # log the rejection, do not raise
```

A test asserts that "diabetic" never lands in the table regardless of what the model sends.

### 5.3 Blocked topics

| Topic | Response |
|---|---|
| MEDICAL | acknowledge generically, recommend a qualified professional, offer what it can help with |
| FOOD_SAFETY | decline, point to food safety authorities, offer something adjacent |
| OFF_TOPIC | warm redirect, never scolding |

These render as ordinary assistant messages, not error states. Marcus explicitly did not want a narc.

**Food-adjacent is in scope**: wine, equipment, hosting, restaurants, technique.

### 5.4 Allergen notice

Every response naming a recipe or ingredient carries `allergen_notice: true`. The frontend renders it as chrome attached to the message. **The model never writes it.** This keeps it consistent, which was Diane's stated concern, and keeps the assistant's voice unhedged, which was Marcus's.

In the build this widened to every substantive reply. A heuristic that decides when a reply names an ingredient will eventually be wrong, and being wrong once is the thing counsel wrote the email about. Only declines are exempt.

## 6. Personality

Not decoration. It is Marcus's strongest ask and Jordan's interviews confirm it drives retention. Lives in `app/prompts.py` as a real artifact with few-shot examples.

Voice rules:
- Has opinions and states them. "Don't make that, make this instead" is in range.
- No "As an AI", no "It's important to note", no disclaimer stacking
- Recommends one thing confidently rather than listing five options
- Asks about equipment naturally, in passing, not as an interrogation
- Brief. A friend who cooks doesn't lecture.

## 7. API

| Method | Path | Body / returns |
|---|---|---|
| POST | `/api/chat` | `{user_id, message}` → SSE stream of tokens, then a final event with `{allergen_notice, sources, recipe}` |
| GET | `/api/profile/{user_id}` | `{cookware, likes, dislikes, avoid}` |
| PATCH | `/api/profile/{user_id}` | partial update from the UI |
| DELETE | `/api/profile/{user_id}` | Diane's deletion requirement. Profile, conversation thread and saved recipes together |
| POST | `/api/recipes/{user_id}` | a recipe body → 201 with the stored id |
| GET | `/api/recipes/{user_id}` | saved recipes, newest first |
| DELETE | `/api/recipes/{user_id}/{recipe_id}` | remove one, if it belongs to this user |
| GET | `/health` | compose healthcheck |

## 8. Robustness

The README promises testing with inputs we didn't design for. Required handling:

| Input / condition | Expected |
|---|---|
| empty or whitespace message | 422, no model call |
| very long message | truncate or 413, never a 500 |
| prompt injection at the policy layer | classifier still blocks; it runs before the model sees anything |
| LLM API failure or timeout | graceful message, 503, no stack trace to the client |
| search failure | agent continues without it |
| database unavailable | chat still answers, memory degrades, clearly stated |
| concurrent requests, same user | no lost profile writes |
| non-English input | answers or redirects, does not crash |
| agent tool loop | hard cap at 5 iterations |

## 9. Tests

**Unit.** No network, no database, runs in seconds.
- classifier routes each topic, including adversarial phrasings
- `save_profile` strips medical terms; "diabetic" never reaches the table
- profile merge deduplicates and preserves existing entries
- `needs_allergen_notice` fires on recipe text, not on a substitution answer

**Integration.** Real app, mocked LLM and search.
- `/api/chat` streams and returns a well-formed contract
- memory round trip: state a fact, get it back on a later request
- blocked topics never reach the agent node
- `DELETE /api/profile` empties it
- malformed and empty payloads return 4xx, not 500

Never assert on generated prose. Assert on structure and on what must be absent.

## 10. Out of scope

PDF cookbook ingestion · grocery list export · hands-free voice · live restaurant lookup · authentication · medical or dietary adaptation · food safety guidance.

Saved favorites were on this list and came off it. They shipped once structured recipe output made a saved card worth something. `TRADEOFFS.md` has the argument.

Reasoning for each is in `SCOPING.md`. Voice keeps one architectural accommodation: the reply text is a separate field from UI chrome, so a TTS layer can consume it later without restructuring.

## 11. Demo path

A grader clones, runs, and sees an empty profile. The memory feature is invisible unless shown. `README.md` must include a scripted two-message sequence that makes it obvious in under a minute:

```
1. "I only have a hot plate and one pan"
2. "what's for dinner?"        → suggests something that works in one pan
3. restart containers
4. "what's for dinner?"        → still knows
```
