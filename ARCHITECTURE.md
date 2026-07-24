# PantryPal v1 — Architecture

Diagrams for the system specified in `PRD.md`. Every element here traces back to that document; nothing is invented. Reasoning behind the decisions lives in `SCOPING.md`.

---

## 1. System overview

```mermaid
graph TB
    User[Browser user]

    subgraph compose[Docker Compose]
        FE[React and Vite frontend]
        BE[FastAPI backend with LangGraph]
        DB[(Postgres 16)]
    end

    subgraph ext[External APIs]
        GEM[Gemini Flash and Pro]
        TAV[Tavily search]
    end

    User --> FE
    FE -->|POST /api/chat over SSE| BE
    FE -->|GET PATCH DELETE /api/profile| BE
    BE -->|profiles table| DB
    BE -->|LangGraph checkpointer keyed by thread| DB
    BE -->|langchain-google-genai| GEM
    BE -->|langchain-tavily| TAV
```

Three Compose services and two outbound dependencies. The frontend never talks to Postgres or to either external API directly — everything goes through FastAPI, which is what makes the write guard in diagram 4 unavoidable rather than advisory. Postgres carries two distinct workloads: the structured `profiles` table and the LangGraph conversation checkpointer. Both Gemini tiers are reached through LangChain, never a vendor SDK, which is a hard README requirement. `/health` exists for the Compose healthcheck. Note that if Postgres is unavailable the chat still answers with memory degraded and the degradation stated to the user, so the DB edges are not on the critical path for a reply.

---

## 2. Request flow through the graph

```mermaid
flowchart TD
    A[POST /api/chat] --> V{Payload valid}
    V -->|empty or whitespace| R422[422 with no model call]
    V -->|very long| R413[Truncate or 413]
    V -->|ok| C[Classify with one Flash call]
    C --> CT{Topic is OK}

    CT -->|no| BLK[Canned safe response]
    BLK --> STR[SSE stream]

    CT -->|yes| D{Difficulty}
    D -->|SIMPLE| FL[Gemini Flash]
    D -->|HARD| PR[Gemini Pro]
    FL --> AG[LangGraph agent node]
    PR --> AG

    AG --> TC{Model requests a tool}
    TC -->|yes| TL[search_web or get_user_profile or remember_about_user]
    TL --> IT{Under 5 iterations}
    IT -->|yes| AG
    IT -->|no| FIN[Finalize answer]
    TC -->|no| FIN

    FIN --> AN[Attach allergen_notice if a recipe or ingredient is named]
    AN --> STR
    STR --> EV[Final event with allergen_notice and sources]

    classDef blocked fill:#fadbd8,stroke:#922b21,color:#641e16
    class BLK blocked
```

One classifier call returns topic and difficulty together, so the policy check costs nothing extra on top of routing. The blocked branch, shaded, short-circuits before any model sees the user's text — that ordering is what makes the policy layer resistant to prompt injection, since the classifier runs first and the agent node never executes. On the allowed path, difficulty picks the tier and the agent loops freely: the model chooses which of the three tools to call and in what order, and there is no fixed sequence anywhere in the graph. The only ceiling is the hard cap of 5 iterations. The allergen notice is attached by the server after the answer is settled, never authored by the model.

---

## 3. Policy decision tree

```mermaid
flowchart TD
    IN[Incoming message] --> CL[Classifier one Flash call]
    CL --> Q{Topic}

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
    class M1,M2,M3,S1,S2,S3,O1,MSG,STOP blocked
```

Four outcomes, three of which terminate before the agent. The shape of every decline is the same: acknowledge, redirect to the right authority, then immediately offer something useful — the same never-bare-refuse pattern used when a recipe does not fit the user's cookware. These render as normal assistant turns, not error states, because the CEO explicitly did not want the product to read as a narc. The `OK` branch is deliberately generous: wine, equipment, hosting, restaurants, and technique all resolve to `OK` and reach the agent. Restaurant *discussion* is in scope; live restaurant lookup is not built. The boundary is model-judged rather than deterministic, which is an accepted risk recorded in `SCOPING.md`.

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

This is the diagram that reconciles the CEO's headline memory feature with counsel's data restriction, and it is the most load-bearing part of the build. Three tiers. Preferences and equipment persist normally. An allergy persists as a behavioral exclusion only — `shellfish` lands in `avoid` as a bare ingredient name, with the reason it is there deliberately not recorded, which delivers "don't suggest shrimp" while storing a filter rule rather than a diagnosis. Medical conditions are never written: acknowledged in the reply, pointed to a professional, dropped before SQL.

The critical property is that `remember_about_user` is model-driven, so the model *will* eventually attempt to write a condition. The prompt is not the defense — `save_profile` is, and it strips matches against `MEDICAL_TERMS` on every path, including the ones the model believes are safe. Rejections are logged and the tool still returns successfully, so a blocked write never surfaces to the user as a failure. Two things make this structural rather than conventional: the guard sits on the only write path, and the schema has no medical column to write into even if the guard were bypassed. A test asserts that "diabetic" never reaches the table regardless of what the model sends.

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
    participant P as Postgres
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
    G-->>A: answer tokens for a one pan dish
    A-->>F: token chunks
    F-->>R: SSE token events
    R-->>U: reply renders as it streams

    F->>F: needs_allergen_notice returns true
    F->>P: write checkpoint
    F-->>R: final event with allergen_notice and sources
    R-->>U: allergen chrome attached to the message
```

A realistic turn, and the one the demo script in `PRD.md` section 11 exercises. The agent takes three passes through the model: read the profile, write the new cookware fact, then answer. Nothing forces that order — the model chose to read before answering and to persist the hot plate on its own, and a different turn would produce a different call pattern or none at all. The saved cookware is what makes the same question answerable after a container restart, which is the point of the scripted demo. Note the two-part response contract: tokens stream first so time-to-first-token stays low, then a single final event carries `allergen_notice` and `sources`. The notice is computed server-side by `needs_allergen_notice`, which keeps it consistent by construction and keeps the assistant's prose unhedged.

---

## Reading order

Diagram 1 for what runs where. Diagram 2 for the path of a single request. Diagrams 3 and 4 are the two hard legal boundaries — 3 covers what the assistant will not discuss, 4 covers what the system will not store. Diagram 5 shows the whole thing working on the demo case.
