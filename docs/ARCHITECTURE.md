# PantryPal v1: Architecture

Diagrams of the system as it shipped, redrawn after the build. They started as diagrams of the spec in `PRD.md` and drifted, so they now follow the code rather than the plan. Reasoning behind the decisions lives in `SCOPING.md`, and what the plan got wrong is listed there under "Where this document drifted."

---

## 1. System overview

```mermaid
graph TB
    User[Browser user]

    subgraph compose[Docker Compose]
        FE[React and Vite frontend]
        BE[FastAPI backend with LangGraph]
        DB[(SQLite file on a volume)]
    end

    subgraph ext[External APIs]
        GEM[Gemini flash-lite fast and smart tiers]
        TAV[Tavily search]
    end

    User --> FE
    FE -->|POST /api/chat over SSE| BE
    FE -->|GET PATCH DELETE /api/profile| BE
    FE -->|POST GET DELETE /api/recipes| BE
    BE -->|profiles table| DB
    BE -->|saved_recipes table| DB
    BE -->|LangGraph checkpointer keyed by thread| DB
    BE -->|langchain-google-genai| GEM
    BE -->|langchain-tavily| TAV
```

Two Compose services and two outbound dependencies. The frontend never talks to the database or to either external API directly. Everything goes through FastAPI, which is what makes the write guard in diagram 4 unavoidable rather than advisory. SQLite carries three workloads: the structured `profiles` table, the `saved_recipes` table, and the LangGraph conversation checkpointer. All three matter to diagram 6, because a deletion request has to clear all of them. Both Gemini tiers are reached through LangChain, never a vendor SDK, which is a hard README requirement. Both are flash-lite models, since every Pro tier is quota-zero on a free key. `/health` exists for the Compose healthcheck. If the database is unavailable the chat still answers with memory degraded and says so, so the DB edges are not on the critical path for a reply.

---

## 2. Request flow through the graph

```mermaid
flowchart TD
    A[POST /api/chat] --> V{Payload valid}
    V -->|empty or whitespace| R422[422 with no model call]
    V -->|over 4000 chars| R413[413, never a 500]
    V -->|ok| KW{keyword_topic regex pass}

    KW -->|FOOD_SAFETY or MEDICAL| BLK[Canned decline, zero API calls]
    KW -->|no match| C[classify, one classifier call]
    C --> CT{Topic is OK}

    CT -->|no| BLK
    BLK --> STR[SSE stream]

    CT -->|yes| D{Difficulty}
    D -->|SIMPLE| FL[Fast tier]
    D -->|HARD| PR[Smart tier]
    FL --> AG[LangGraph agent node]
    PR --> AG

    AG --> TC{Model requests a tool}
    TC -->|yes| TL[search_web, get_user_profile, remember_about_user or present_recipe]
    TL --> IT{Under 5 iterations}
    IT -->|yes| AG
    IT -->|no| FIN[finalize node]
    TC -->|no| FIN

    FIN --> AN[Attach allergen_notice, plus the recipe card if one was presented]
    AN --> STR
    STR --> EV[Final event with allergen_notice, sources and recipe]

    classDef blocked fill:#fadbd8,stroke:#922b21,color:#641e16
    class KW,BLK blocked
```

Two gates, in this order, and the order is the point. A regex pass runs first and costs nothing, so an obvious food-safety or medical question is declined without any API call at all and without the message ever being handed to a model that could be argued with. Only what the regex does not recognise reaches `classify()`, which returns topic and difficulty together, so the policy check costs nothing extra on top of routing.

The blocked branches, shaded, short-circuit before the agent node executes. On the allowed path, difficulty picks the tier and the agent loops freely: the model chooses which of the four tools to call and in what order, and there is no fixed sequence anywhere in the graph. The only ceiling is the hard cap of 5 iterations, which all four tools now share.

The allergen notice is attached by the server after the answer is settled, never authored by the model. It fires on every substantive reply rather than on a judgment about whether one named an ingredient, and it fires if a recipe card is present even when the prose alone would not have triggered it.

---

## 3. Policy decision tree

```mermaid
flowchart TD
    IN[Incoming message] --> KW[keyword_topic regex pass, no API call]
    KW --> KQ{Obvious match}
    KQ -->|FOOD_SAFETY or MEDICAL| Q{Topic}
    KQ -->|nothing matched| CE{Classifier reachable}
    CE -->|yes| CL[classify, one classifier call]
    CE -->|no| FO[Fails open to OK and SIMPLE]
    CL --> Q
    FO --> K1

    Q -->|MEDICAL| M1[Acknowledge generically]
    M1 --> M2[Recommend a qualified professional]
    M2 --> M3[Offer what it can help with]

    Q -->|FOOD_SAFETY| S1[Decline the judgment]
    S1 --> S2[Point to food safety authorities]
    S2 --> S3[Offer something adjacent]

    Q -->|OFF_TOPIC| O1[Warm redirect never scolding]

    Q -->|OK| K1[Cooking question or food adjacent]
    K1 --> K2[Wine equipment hosting restaurants technique]
    K2 --> GO[Model selection then agent node]

    M3 --> MSG[Rendered as an ordinary assistant message]
    S3 --> MSG
    O1 --> MSG
    MSG --> STOP[Agent node never runs]

    classDef blocked fill:#fadbd8,stroke:#922b21,color:#641e16
    class KW,M1,M2,M3,S1,S2,S3,O1,MSG,STOP blocked
    classDef degraded fill:#fdf2d0,stroke:#9c6f19,color:#5c4108
    class FO degraded
```

Four outcomes, three of which terminate before the agent. The regex pass at the top is the part worth reading twice: it runs before any model call, so instruction-shaped text in the message has nothing to argue with, and an obvious block costs zero API quota. Only unmatched messages reach the classifier.

The shaded amber node is the honest part. `classify()` fails open to OK when the classifier is unreachable, which means a degraded classifier lets through anything the regex did not already catch. That is a deliberate choice, because failing closed would turn a model outage into a product that declines every question, but it is the reason the regex layer exists at all. It also falls unevenly: the regexes are English, so a non-English speaker loses the backstop that an English speaker keeps. That is written up in `TRADEOFFS.md`.

The shape of every decline is the same: acknowledge, redirect to the right authority, then immediately offer something useful, which is the never-bare-refuse pattern also used when a recipe does not fit the user's cookware. These render as normal assistant turns, not error states, because the CEO explicitly did not want the product to read as a narc. The `OK` branch is deliberately generous: wine, equipment, hosting, restaurants, and technique all resolve to `OK` and reach the agent. Restaurant *discussion* is in scope; live restaurant lookup is not built.

---

## 4. Profile write path

```mermaid
flowchart TD
    U[User states a fact in chat] --> MC[Model calls remember_about_user]
    MC --> F{Which field}

    F -->|cookware likes dislikes| T1[Tier 1 store freely]
    F -->|avoid| T2[Tier 2 store as a rule]
    F -->|medical phrasing| T3[Tier 3 never store]

    T2 --> NM[Reduce to a plain ingredient name]
    NM --> NR[No medical reasoning attached]

    T1 --> GD[save_profile write guard]
    NR --> GD
    T3 --> GD

    GD --> CK{Value matches MEDICAL_TERMS}
    CK -->|no| MG[Merge dedupe and preserve existing]
    MG --> DB[(profiles table)]
    DB --> OKR[Tool returns success]

    CK -->|yes| DR[Strip value before it reaches SQL]
    DR --> LG[Log the rejection and do not raise]
    LG --> OKR
    LG --> AC[Turn acknowledges and points to a professional]

    NOTE[No medical column exists in the schema] --- DB

    classDef blocked fill:#fadbd8,stroke:#922b21,color:#641e16
    class T3,DR,LG,AC blocked
```

This is the diagram that reconciles the CEO's headline memory feature with counsel's data restriction, and it is the most load-bearing part of the build. Three tiers. Preferences and equipment persist normally. An allergy persists as a behavioral exclusion only. `shellfish` lands in `avoid` as a bare ingredient name, with the reason it is there deliberately not recorded, which delivers "don't suggest shrimp" while storing a filter rule rather than a diagnosis. Medical conditions are never written: acknowledged in the reply, pointed to a professional, dropped before SQL.

The property that matters is that `remember_about_user` is model-driven, so the model will eventually attempt to write a condition. The prompt is not the defense. `save_profile` is, and it strips matches against `MEDICAL_TERMS` on every path, including the ones the model believes are safe. Rejections are logged and the tool still returns successfully, so a blocked write never surfaces to the user as a failure. Two things make this structural rather than conventional: the guard sits on the only write path, and the schema has no medical column to write into even if the guard were bypassed. A test asserts that "diabetic" never reaches the table regardless of what the model sends.

The limit of the diagram is the `CK` node. `MEDICAL_TERMS` is a finite list, so what it does not recognise it does not strip. The guard cannot be bypassed or argued out of, but it can be walked around by a phrasing nobody thought of. `TRADEOFFS.md` says which phrasings, and why widening the list is harder than it looks.

---

## 5. Chat turn sequence

```mermaid
sequenceDiagram
    participant U as User
    participant R as React
    participant F as FastAPI
    participant C as Classifier
    participant A as LangGraph Agent
    participant T as Tools
    participant P as SQLite
    participant G as Gemini

    U->>R: I only have a hot plate and one pan, what is for dinner
    R->>F: POST /api/chat with user_id and message
    F->>C: classify
    C->>G: single Flash call
    G-->>C: topic OK and difficulty SIMPLE
    C-->>F: allowed, route to Flash
    F->>P: load checkpoint for thread
    P-->>F: prior turns trimmed to last 10
    F->>A: invoke agent with three tools bound

    A->>G: iteration 1
    G-->>A: call get_user_profile
    A->>T: get_user_profile
    T->>P: select from profiles
    P-->>T: cookware likes dislikes avoid
    T-->>A: profile

    A->>G: iteration 2 with profile in context
    G-->>A: call remember_about_user with cookware hot plate and one pan
    A->>T: remember_about_user
    T->>T: save_profile write guard passes
    T->>P: merge into cookware
    P-->>T: updated
    T-->>A: saved

    A->>G: iteration 3
    G-->>A: call present_recipe with a one pan dish
    A->>T: present_recipe
    T-->>A: card recorded for this turn

    A->>G: iteration 4
    G-->>A: answer tokens alongside the card
    A-->>F: token chunks
    F-->>R: SSE token events
    R-->>U: reply renders as it streams

    F->>F: needs_allergen_notice returns true
    F->>P: write checkpoint
    F-->>R: final event with allergen_notice, sources and recipe
    R-->>U: allergen chrome plus a recipe card the user can save
```

A realistic turn, and the one the demo script in `PRD.md` section 11 exercises. The agent takes four passes through the model here: read the profile, write the new cookware fact, present the card, then answer. Nothing forces that order. The model chose to read before answering and to persist the hot plate on its own, and a different turn would produce a different call pattern or none at all. Most turns call no tools and carry no card.

The saved cookware is what makes the same question answerable after a container restart, which is the point of the scripted demo. Note the two-part response contract: tokens stream first so time-to-first-token stays low, then a single final event carries `allergen_notice`, `sources` and `recipe`. The notice is computed server-side by `needs_allergen_notice`, which keeps it consistent by construction and keeps the assistant's prose unhedged.

This is also where the four-tool loop starts to press against its ceiling. Four passes fits inside the cap of 5, but a turn that searched twice before finding a recipe worth showing would not have room left to present it.

---

## 6. Deletion across three stores

```mermaid
flowchart TD
    D[DELETE /api/profile/user_id] --> C1[forget_conversation, checkpointer rows]
    C1 --> C2[saved_recipes.delete_all]
    C2 --> C3[delete_profile, profiles row]
    C3 --> ALL{All three reported success}

    ALL -->|yes| OK204[204 No Content]
    ALL -->|no| E503[503, and the message says some of it may still be stored]

    E503 --> RETRY[Every delete is idempotent, so a retry converges]
    RETRY -.-> D

    classDef legal fill:#fadbd8,stroke:#922b21,color:#641e16
    class E503,OK204 legal
```

The one route where a lie costs more than a failure. Three stores have to be cleared and they cannot share a transaction, because the checkpointer owns its own connection and SQLite has no cross-connection transaction. So the design gives up atomicity and buys convergence instead: every delete is idempotent, the conversation goes first, and the route answers 204 only when all three succeeded. A partial failure leaves a retry that finishes the job.

The ordering is deliberate. The conversation transcript is the store most likely to contain something the profile write guard refused to record, so it goes first and a failure part way through leaves the least sensitive material behind rather than the most.

This route had a real bug that a green test suite did not catch: `delete_profile` returned success even when its write threw, so the route answered 204 over data that was still stored. `TRADEOFFS.md` has the account of how that survived.

---

## Reading order

Diagram 1 for what runs where. Diagram 2 for the path of a single request. Diagrams 3, 4 and 6 are the legal boundaries: 3 covers what the assistant will not discuss, 4 covers what the system will not store, and 6 covers what it has to be able to erase. Diagram 5 shows the whole thing working on the demo case.
