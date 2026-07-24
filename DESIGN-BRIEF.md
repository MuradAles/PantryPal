# PantryPal — design brief

Working file. Not committed, not part of the submission.

Direction is taken from the logo and the mockup: warm cream ground, terracotta accent, serif for anything editorial, a recipe that reads like a page from a cookbook rather than a chat message.

---

## 1. Direction

**Palette** — read off the logo and mockup.

| Role | Hex | Use |
|---|---|---|
| Cream ground | `#F7F3EA` | page background |
| Card | `#FFFFFF` | the recipe card and the conversation surface |
| Terracotta | `#B4593C` | accent: user bubble, section headings, active nav, primary button |
| Terracotta wash | `#F0E2DA` | hover, active row, tag fill |
| Ink | `#2B2320` | body text |
| Ink muted | `#7A6E66` | meta, captions, timestamps |
| Sage | `#DCE5D6` | preference tags |
| Notice | `#EDF1F3` | allergen notice ground |

**Type — two roles, both doing real work.**

- *Editorial serif* for recipe titles, section headings (`Ingredients`, `Preparation`), and panel headings. A transitional serif with warmth, not a high-contrast fashion face. This carries the cookbook feeling.
- *Clean sans* for UI, meta rows, tags, buttons, and the assistant's conversational prose.
- Small caps with wide letterspacing for meta and labels: `35 MINS · EASY · SERVES 4`, `SOURCES & INSPIRATION`, `AVAILABLE PANTRY`.

**Motifs worth keeping from the mockup**

- Ghosted step numbers (`01`, `02`) in the left gutter of the method, terracotta at low opacity.
- Ingredients in two columns with small terracotta bullets.
- The recipe as a bordered white card floating on cream — visually a different object from the conversation around it.
- Sources as small bordered pill chips, uppercase, with an external-link glyph.
- The allergen notice as a quiet tinted box with an `ⓘ`, never a red alert.

---

## 2. Where the mockup and the app disagree

The mockup shows a more finished product than exists. These have to be resolved before a design can drop in.

| In the mockup | Reality | What to do |
|---|---|---|
| Nav: Home / Recipes / Groceries / Favorites | None exist. Groceries and Favourites were explicitly cut in `SCOPING.md` | Drop the nav. Wordmark only. |
| "Chat History" sidebar with past conversations | One persistent thread per user. There is no conversation list. | Drop the left rail. Two columns, not three. |
| Recipe photography | No image generation, no image search | Recipe card is typographic. This is a feature, not a lack — it makes the type carry the page. |
| Pantry with quantities (`2 cans`, `2kg`) | Stored facts are names only, no amounts | Tags, not a quantity table. |
| "Recent Successes" | Not tracked | Drop, or leave as a future slot. |
| Recipe title, time, difficulty, servings | The model writes free markdown; none of this is structured | Style `h1`/`h2` inside the reply so a recipe *looks* like this when the model produces one. Do not design a card that requires fields the data does not have. |

**The one structural note:** the assistant's reply is a single markdown blob. The cookbook look has to come from styling `h1`–`h3`, `ul`, `ol` and `strong` inside `.message-assistant .bubble` — not from a component with title/time/servings props. Design it as a *styled document*, not a data-driven card.

---

## 3. Screens

**Header.** Slim, cream, wordmark in terracotta serif. Nothing else.

**Left, ~68% — conversation.**
- User turns: terracotta fill, cream text, rounded, right-aligned, comfortable max-width.
- Assistant turns: white card on cream, generous padding, left-aligned. Small terracotta eyebrow `✦ PANTRYPAL` above the first line.
- Inside an assistant turn, markdown styled as a cookbook page: serif headings in terracotta, two-column ingredient lists, numbered method with ghosted gutter numerals.
- Streaming: a quiet "Thinking…" line. No spinner.
- Allergen notice: tinted box at the foot of the card, inside its border, above sources.
- Sources: `SOURCES & INSPIRATION` in small caps, then pill chips.
- Empty state: serif headline, two short paragraphs, on cream. This is the first thing a new user sees.
- Composer: pinned at the bottom, white field on cream, terracotta Send. Becomes Stop while streaming.

**Right, ~300px — the memory panel.**
- Serif heading `What I know about you`, one line of explanation beneath.
- Four groups: Cookware, Likes, Dislikes, Avoids. Small-caps labels, soft tag pills.
- Sage fill for likes, neutral for cookware and dislikes, terracotta wash for avoids — avoids matter most.
- Empty group reads `nothing yet`, quietly. Not an error.
- A tag appearing mid-conversation should be noticeable. This is the feature that proves the product remembers you.
- `Delete everything` at the bottom, always visible, two-step inline confirm.

---

## 4. States to design

First visit (both columns empty) · streaming mid-reply · a long recipe with notice and sources · a blocked-topic reply, which is an ordinary assistant message and must **not** look like an error · a backend error, which must · a tag appearing · mobile with the panel as a drawer, delete still reachable inside it.

---

## 5. Non-negotiable

- **The allergen notice appears on nearly every reply.** Quiet and habitual. If it reads as a warning it becomes noise within three messages and fights the voice.
- **Delete everything must stay reachable at mobile width.**
- Body text must survive a 1200-character recipe without feeling cramped.

---

## 6. Prompt to paste

```
Design PantryPal, an AI cooking assistant. Web app, desktop-first, responsive.
It is the friend who actually cooks: warm, opinionated, brief. Never a
corporate chatbot.

BRAND
Warm cream ground #F7F3EA, white cards, terracotta accent #B4593C, ink #2B2320,
muted ink #7A6E66, sage #DCE5D6 for tags, #EDF1F3 for the notice box.
Editorial serif for recipe titles, section headings and panel headings — a warm
transitional serif, not a high-contrast fashion face. Clean sans for UI, meta
and conversational prose. Small caps with wide tracking for labels.

LAYOUT — two columns under a slim header holding only the wordmark.
No nav. No conversation-history sidebar.

LEFT, conversation:
- User turns: terracotta fill, cream text, rounded, right-aligned.
- Assistant turns: white card on cream, generous padding, small terracotta
  eyebrow reading PANTRYPAL above the first line.
- When a reply contains a recipe it must read like a page from a cookbook:
  serif headings in terracotta, ingredients in two columns with small terracotta
  bullets, method as numbered steps with ghosted 01/02 numerals in the left
  gutter. This comes from styling markdown h1-h3, ul, ol and strong inside the
  assistant card — NOT from a component with title/time/servings fields.
- Allergen notice: a quiet tinted box with an info glyph at the foot of the
  card. It appears on almost every reply, so it must be ignorable but always
  present. Never red, never an alert.
- Sources: SOURCES & INSPIRATION in small caps, then small bordered pill chips
  with an external-link glyph.
- Empty state: serif headline plus two short paragraphs on cream.
- Composer pinned at the bottom: white field, terracotta Send, becomes Stop
  while a reply streams.

RIGHT, about 300px, the memory panel:
- Serif heading "What I know about you" and one line of explanation.
- Four groups with small-caps labels: Cookware, Likes, Dislikes, Avoids.
- Soft tag pills. Sage for likes, neutral for cookware and dislikes, terracotta
  wash for avoids. Sample: Cookware "hot plate", "one pan"; Likes "thai",
  "spicy"; Avoids "shellfish".
- Empty group reads "nothing yet", quietly, not as an error.
- "Delete everything" at the bottom, always visible, two-step inline confirm.

ALSO PRODUCE
- Mobile: right panel becomes a drawer from a header control, delete still
  reachable inside it.
- The empty first-run state alone.
- A long recipe reply with the notice and a sources row.

AVOID
Purple-blue AI gradients. Robot or sparkle iconography. iMessage-style bubbles.
Food photography — the design must work on type alone.

OUTPUT
Plain CSS only. No framework, no JSX, no component code. Key every rule to
these exact class names so it drops into the existing app unchanged:

  app, app-header, columns
  chat, transcript, messages, empty-state
  message, message-user, message-assistant, bubble, generating
  allergen-notice, sources, stream-error
  composer, visually-hidden
  profile, profile-note, profile-group, profile-empty, tags, tag, profile-delete

Also style markdown inside .message-assistant .bubble: h1, h2, h3, ul, ol, li,
strong, p.
```

---

## 7. Applying the result

Replace `frontend/src/styles.css`. Add a font link to `frontend/index.html` if needed.

**Take only CSS.** If the tool returns components, discard them — the current ones carry the allergen-notice-from-flag guarantee and the SSE parsing, and regenerating them would silently drop both.
