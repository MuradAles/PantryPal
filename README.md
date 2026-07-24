# PantryPal

An AI cooking assistant. Ask it what to cook, it answers, and it remembers your kitchen between sessions so it never suggests something you cannot actually make.

Built for the PressW Applied AI Engineer assessment. The reasoning behind every scoping decision is in [SCOPING.md](SCOPING.md), and an honest account of what is still wrong with it is in [TRADEOFFS.md](TRADEOFFS.md).

---

## Running it

You need Docker, and two API keys.

```bash
cp .env.example .env
```

Then fill in two values in `.env`:

| Variable | Where to get it |
|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey), free tier is fine |
| `TAVILY_API_KEY` | [tavily.com](https://tavily.com), free tier is fine |

Leave the model ids alone unless you want to change them. Then:

```bash
docker compose up -d --build
```

Open **http://localhost:5173**. The API is on port 8000.

```bash
curl localhost:8000/health
# {"status":"ok","database":true}
```

### One thing that will catch you out

If you edit `.env` after the containers exist, a plain `restart` will not pick up the change. Docker Compose bakes `env_file` at container creation.

```bash
docker compose up -d --force-recreate backend
```

This cost us an hour during the build, and the failure is confusing: the container keeps running the old values while the file on disk says something else.

---

## See it work in a minute

The interesting part is the memory, and it is invisible until you give it something to remember. Type these two messages in order and watch the right-hand panel.

```
1.  I only have a hot plate and one pan
        ->  "hot plate" and "one pan" appear under Cookware.
            Nobody asked it to save those. The model decided to.

2.  what's for dinner?
        ->  a suggestion that works in one pan, because it now
            knows what you own.
```

Then restart the containers and ask again. It still knows.

Two more worth trying, both of which cost zero API calls because they never reach a model:

```
3.  is this chicken from Tuesday still safe to eat?
        ->  a warm decline pointing at food safety authorities

4.  write my cover letter
        ->  a friendly redirect back to food
```

And two that show the boundaries are generous rather than brittle:

```
5.  what wine goes with lamb?          ->  answered, food-adjacent is in scope
6.  I'm allergic to shellfish          ->  saved to Avoids, never suggested again
```

---

## Using the API directly

```bash
# stream a reply
curl -N -X POST localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"you","message":"I only have a hot plate and one pan"}'
```

Replies arrive as server-sent events: `token` events while generating, then exactly one `done` event carrying the response contract.

```
event: token
data: {"text": "Carbonara, then. Boil the pasta in the pan"}

event: done
data: {"allergen_notice": true, "sources": []}
```

```bash
# what it remembers about you
curl localhost:8000/api/profile/you

# edit one field, leaving the others alone
curl -X PATCH localhost:8000/api/profile/you \
  -H 'Content-Type: application/json' -d '{"likes":["thai"]}'

# erase everything, profile and conversation history together
curl -X DELETE localhost:8000/api/profile/you
```

| Method | Path | Does |
|---|---|---|
| `POST` | `/api/chat` | Send a message, stream the reply |
| `GET` | `/api/profile/{user_id}` | Everything stored about a user |
| `PATCH` | `/api/profile/{user_id}` | Overwrite named fields only |
| `DELETE` | `/api/profile/{user_id}` | Erase the profile and the conversation thread |
| `GET` | `/health` | Liveness, plus whether the database is reachable |

---

## Tests

```bash
docker compose exec backend pytest -q
# 168 passed
```

They run in about two seconds and cost nothing, because every model in the suite is scripted locally in `backend/tests/fakes.py`. No test reaches a real API.

The ones that matter most are `tests/unit/test_profile_guard.py`, which asserts that a medical condition never reaches storage no matter what the model sends, and `tests/integration/test_policy_and_memory.py`, which asserts that blocked topics never reach the model at all. Both have been mutation-checked: break the code underneath them and they go red.

---

## How it works

```
POST /api/chat
  |
  v
classify           keyword pass first, then one small model call
  |                returns { topic, difficulty }
  |
  +-- topic blocked --> canned decline, streamed, model never invoked
  |
  v
pick a model       SIMPLE -> fast tier, HARD -> smart tier
  |
  v
LangGraph agent    tools bound, loops up to 5 times
  |  ^
  |  |  search_web / get_user_profile / remember_about_user
  +--+
  |
  v
attach allergen notice, stream tokens
```

The model chooses its own tool calls. Nothing in the code inspects the user's message and calls a tool on its behalf.

**Three things are enforced in code rather than asked for in a prompt**, because counsel called them non-negotiable and a prompt is a request:

- Blocked topics are caught by a regex pass that runs before any model, so no amount of instruction-shaped text in a message can argue past it.
- `save_profile` strips medical terms before they reach SQL, and the schema has no column a condition could live in anyway.
- The allergen notice is computed server-side and rendered by the frontend from a boolean. The model never writes it, cannot reword it, and cannot suppress it.

---

## Layout

```
backend/app/
  main.py       FastAPI, SSE streaming, the five routes
  graph.py      the LangGraph agent and the classify-then-route gate
  policy.py     keyword layer, classifier, medical denylist, allergen rule
  profile.py    the three memory tiers and the write guard
  tools.py      the three tools the model may call
  llm.py        the only file that names a model provider
  prompts.py    the persona, as a real artifact with worked examples
  db.py         the only file that touches storage
  config.py     environment settings

frontend/src/   React, deliberately unstyled pending a design

docs/           PRD, build checklist, architecture diagrams, the original brief
brief/          the four stakeholder artifacts this was scoped from
```

---

## What it will not do

It declines medical and dietary questions, and it will not rule on whether food is safe to eat. Both are hard limits from counsel, and both decline warmly with an offer of what it can help with instead rather than refusing flat.

It is generous about what counts as food. Wine, equipment, hosting, restaurants and technique are all in scope.

Known gaps, including the ones a reviewer is most likely to find, are written up in [TRADEOFFS.md](TRADEOFFS.md).
