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

Nothing else to install. Tailwind is a dev dependency Vite builds inside the container. The three webfonts load from Google Fonts at runtime, so on a machine with no internet you get the same layout in fallback faces, with the icon names showing as text.

### One thing that will catch you out

If you edit `.env` after the containers exist, a plain `restart` will not pick up the change. Docker Compose bakes `env_file` at container creation.

```bash
docker compose up -d --force-recreate backend
```

This cost us an hour during the build, and the failure is confusing: the container keeps running the old values while the file on disk says something else.

---

## See it work in a minute

The interesting part is the memory, and it is invisible until you give it something to remember. Type these two messages in order and watch the Memory Bank panel on the right. That panel is only pinned open on a window 1280px or wider. Narrower than that, it lives behind the Profile tab in the bottom bar, which is worth knowing if you are on a laptop sitting right on the boundary.

```
1.  I only have a hot plate and one pan
        ->  "hot plate" and "one pan" appear under Cookware.
            Nobody asked it to save those. The model decided to.

2.  what's for dinner?
        ->  a suggestion that works in one pan, because it now
            knows what you own.
```

Then restart the containers and ask again. It still knows.

If a reply puts a dish on screen as a card rather than as prose, that is the model choosing to call `present_recipe`. Most answers are just conversation and carry no card. When one appears, the bookmark button in its top right corner keeps it, and it shows up in the Saved Recipes rail on the left, newest first. Clicking a row opens the full card and the X removes it. Nothing in the code decides when a card appears. The model does, the same way it decides when to search.

The whole app is one page with three views: Chat, Recipes and Profile. They are tabs held in React state, not routes, so the URL never changes. Above 1280px both side rails are pinned open and the top bar carries Chat and Recipes. Below that the rails collapse and a bottom tab bar appears, which is where Profile lives and how you reach the Memory Bank and the delete control on a small screen.

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
data: {"allergen_notice": true, "sources": [], "recipe": null}
```

`recipe` is null on most turns, because conversation is not a recipe. When the model decides to put a dish on screen it calls `present_recipe`, and the card rides on the same event:

```
event: done
data: {"allergen_notice": true, "sources": [],
       "recipe": {"title": "One-pan carbonara",
                  "ingredients": ["spaghetti", "guanciale", "eggs", "pecorino"],
                  "steps": ["Boil the pasta.", "Render the guanciale.", "Off the heat, toss."],
                  "time_mins": 20, "difficulty": "easy", "serves": 2}}
```

Only `title` and `steps` are guaranteed. `time_mins`, `difficulty` and `serves` come back null when the model did not know them, and the card renders with the slot missing rather than with a number nobody vouched for. That is the same shape `POST /api/recipes` accepts, so a saved card is identical to the one that was shown.

```bash
# what it remembers about you
curl localhost:8000/api/profile/you

# edit one field, leaving the others alone
curl -X PATCH localhost:8000/api/profile/you \
  -H 'Content-Type: application/json' -d '{"likes":["thai"]}'

# erase everything: profile, conversation history and saved recipes
curl -X DELETE localhost:8000/api/profile/you
```

```bash
# keep a recipe
curl -X POST localhost:8000/api/recipes/you \
  -H 'Content-Type: application/json' \
  -d '{"title":"One-pan carbonara","steps":["Boil the pasta."]}'

# what you have kept, newest first
curl localhost:8000/api/recipes/you

# drop one
curl -X DELETE localhost:8000/api/recipes/you/1
```

| Method | Path | Does |
|---|---|---|
| `POST` | `/api/chat` | Send a message, stream the reply |
| `GET` | `/api/profile/{user_id}` | Everything stored about a user |
| `PATCH` | `/api/profile/{user_id}` | Overwrite named fields only |
| `DELETE` | `/api/profile/{user_id}` | Erase the profile, the conversation thread and the saved recipes |
| `POST` | `/api/recipes/{user_id}` | Save a recipe, returns it with its id |
| `GET` | `/api/recipes/{user_id}` | Saved recipes, newest first |
| `DELETE` | `/api/recipes/{user_id}/{recipe_id}` | Remove one, if it belongs to that user |
| `GET` | `/health` | Liveness, plus whether the database is reachable |

There is no authentication, so `user_id` is whatever the client says it is. A delete puts the user id in the SQL `WHERE` clause rather than checking ownership afterwards, so one user cannot remove another's recipe by guessing its id, but anyone who knows a user id can read that account. This is a demo posture, and `TRADEOFFS.md` says so at more length.

---

## Tests

```bash
docker compose exec backend pytest -q
```

The whole suite runs in under two seconds and costs nothing, because every model in it is scripted locally in `backend/tests/fakes.py`. No test reaches a real API.

The ones that matter most are `tests/unit/test_profile_guard.py`, which asserts that a medical condition never reaches storage no matter what the model sends, and `tests/integration/test_policy_and_memory.py`, which asserts that blocked topics never reach the model at all. Both have been mutation-checked: break the code underneath them and they go red.

A green run here is weaker evidence than it looks, and `TRADEOFFS.md` explains why. Two real bugs survived a fully green suite during this build.

---

## How it works

```
POST /api/chat
  |
  v
keyword pass       regex, no API call. Catches the obvious blocks.
  |
  +-- matched --> canned decline, streamed, zero API calls spent
  |
  v
classify           one small model call on whatever is left
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
  |  |  search_web / get_user_profile
  |  |  remember_about_user / present_recipe
  +--+
  |
  v
attach allergen notice and any recipe card, stream tokens
```

The model chooses its own tool calls. Nothing in the code inspects the user's message and calls a tool on its behalf. That includes the recipe card: there is no branch anywhere that reads the message, decides it sounds like a recipe request, and produces one.

**Three things are enforced in code rather than asked for in a prompt**, because counsel called them non-negotiable and a prompt is a request:

- Blocked topics are caught by a regex pass that runs before any model, so no amount of instruction-shaped text in a message can argue past it.
- `save_profile` strips medical terms before they reach SQL, and the schema has no column a condition could live in anyway.
- The allergen notice is computed server-side and rendered by the frontend from a boolean. The model never writes it, cannot reword it, and cannot suppress it.

---

## Layout

```
backend/app/
  main.py       FastAPI, SSE streaming, the eight routes
  graph.py      the LangGraph agent and the classify-then-route gate
  policy.py     keyword layer, classifier, medical denylist, allergen rule
  profile.py    the three memory tiers and the write guard
  recipes.py    saved-recipe storage, ownership in the WHERE clause
  tools.py      the four tools the model may call
  schemas.py    the request and response shapes, including the recipe
  llm.py        the only file that names a model provider, and the backup fallback
  prompts.py    the persona, as a real artifact with worked examples
  db.py         the only file that touches storage
  config.py     environment settings

frontend/src/   React, Tailwind, the chat and the recipe cards

docs/           PRD, build checklist, architecture diagrams, the original brief
brief/          the four stakeholder artifacts this was scoped from
```

---

## What it will not do

It declines medical and dietary questions, and it will not rule on whether food is safe to eat. Both are hard limits from counsel, and both decline warmly with an offer of what it can help with instead rather than refusing flat.

It is generous about what counts as food. Wine, equipment, hosting, restaurants and technique are all in scope.

Known gaps, including the ones a reviewer is most likely to find, are written up in [TRADEOFFS.md](TRADEOFFS.md).
