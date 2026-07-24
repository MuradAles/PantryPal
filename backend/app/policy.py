"""Topic classification, the medical denylist, and the allergen notice rule.

Counsel's three limits are enforced here rather than in the system prompt,
because a prompt is a request and this needs to be a guarantee. Everything in
this module runs before the model sees the message, or after it has finished.

Two layers, deliberately:

1. A deterministic keyword pass. Free, instant, and impossible to talk out of.
   It catches the blunt cases and, because it runs first, a blocked message
   costs no API call at all.
2. An LLM pass for everything the keywords miss — phrasing, implication, tone.

The keyword layer existing means a classifier outage degrades to "slightly more
permissive on subtle cases" rather than to "no legal protection at all".
"""

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app import llm

log = logging.getLogger(__name__)

Topic = Literal["OK", "MEDICAL", "FOOD_SAFETY", "OFF_TOPIC"]
Difficulty = Literal["SIMPLE", "HARD"]


# Conditions the product must never store or reason about. Used both to route a
# message to the MEDICAL decline and, more importantly, to strip values on the
# way into the profile store. See profile.save_profile.
MEDICAL_TERMS: frozenset[str] = frozenset(
    {
        "diabetes", "diabetic", "prediabetic", "insulin", "hypoglycemia", "hyperglycemia",
        "pregnant", "pregnancy", "breastfeeding", "nursing",
        "celiac", "coeliac", "crohn", "colitis", "ibs", "diverticulitis", "gastritis",
        "hypertension", "blood pressure", "cholesterol", "heart disease", "statin",
        "kidney disease", "renal", "dialysis", "liver disease", "fatty liver",
        "cancer", "chemo", "chemotherapy", "radiation",
        "thyroid", "hashimoto", "graves disease",
        "anemia", "anemic", "osteoporosis", "gout",
        "eating disorder", "anorexia", "bulimia",
        "medication", "prescription", "on meds",
        "surgery", "post-op", "recovery diet",
        "cholesterol", "triglycerides", "a1c",
    }
)

# Phrases that mean "rule on whether this is safe to eat". Counsel is absolute
# on this one, and users ask it constantly, so the blunt cases are caught here
# rather than spent on a classifier call.
FOOD_SAFETY_PATTERNS = [
    r"\b(still |it )?(safe|ok|okay|fine|alright) to (eat|consume|serve|use)\b",
    r"\bhas (this|it|that)( \w+)? gone (bad|off)\b",
    r"\b(is|are) (this|it|these|that|they|my)( \w+)? (still )?(good|bad|off|spoiled|rotten|edible)\b",
    r"\bfood poisoning\b",
    r"\bexpir(ed|ation|y)\b",
    r"\buse[- ]by\b",
    r"\bsell[- ]by\b",
    r"\bleft ?out (all night|overnight|for)\b",
    r"\bsmells? (bad|off|weird|funny)\b",
    r"\bmould?y\b",
]

# Signals that a reply named a specific ingredient or dish, which is counsel's
# trigger for the allergen notice. Deliberately broad: showing the notice when
# it was not strictly required costs nothing, missing it once is the risk.
INGREDIENT_SIGNALS = [
    r"\b\d+\s*(g|kg|ml|l|oz|lb|tbsp|tsp|cups?|cloves?|slices?|grams?)\b",
    r"\b(add|stir|fold|whisk|season|simmer|saut[eé]|roast|bake|fry|boil|grill|marinate|toss)\b",
    r"\b(butter|oil|garlic|onion|salt|pepper|flour|egg|eggs|cheese|cream|milk|stock|wine)\b",
    r"\b(chicken|beef|pork|lamb|fish|prawn|shrimp|tofu|beans?|lentils?|rice|pasta|noodles?)\b",
]

_MEDICAL_RE = re.compile("|".join(rf"\b{re.escape(t)}\b" for t in MEDICAL_TERMS), re.I)
_SAFETY_RE = re.compile("|".join(FOOD_SAFETY_PATTERNS), re.I)
_INGREDIENT_RE = re.compile("|".join(INGREDIENT_SIGNALS), re.I)


class Classification(BaseModel):
    """What the classifier decides about one incoming message."""

    topic: Topic = Field(description="OK, MEDICAL, FOOD_SAFETY, or OFF_TOPIC")
    difficulty: Difficulty = Field(description="SIMPLE for a direct question, HARD otherwise")


CLASSIFIER_PROMPT = """\
Classify this message for a cooking assistant. Answer with a topic and a difficulty.

Topic:
- FOOD_SAFETY: asks whether food is safe to eat, spoiled, expired, or will make
  them ill. Any request for a ruling on edibility.
- MEDICAL: mentions a health condition, medication, pregnancy, or asks what to
  eat because of one. Stating a plain preference like "I'm vegetarian" or an
  allergy like "I'm allergic to shellfish" is NOT medical — that is OK.
- OFF_TOPIC: nothing to do with food or eating. Note that wine, kitchen
  equipment, hosting, restaurants, groceries and technique all count as food,
  so those are OK.
- OK: everything else.

Difficulty:
- SIMPLE: one clear question, or small talk.
- HARD: several constraints at once, a plan across multiple dishes, or anything
  needing real reasoning about what the user can actually make.

Message: {message}"""


def keyword_topic(message: str) -> Topic | None:
    """Classify by keyword alone, or return None if nothing obvious matched."""
    # Runs first so an obvious block costs no API call, and so no amount of
    # instruction-shaped text in the message can argue its way past it.
    if _SAFETY_RE.search(message):
        return "FOOD_SAFETY"
    if _MEDICAL_RE.search(message):
        return "MEDICAL"
    return None


async def classify(message: str) -> Classification:
    """Decide the topic and difficulty of one message, keywords first."""
    blocked = keyword_topic(message)
    if blocked:
        log.info("blocked by keyword layer: %s", blocked)
        return Classification(topic=blocked, difficulty="SIMPLE")

    try:
        # Backed by the backup model. The keyword layer above still holds if both
        # are down, but a classifier that is merely out of quota would otherwise
        # fail open on every message for the rest of the day, and failing open is
        # meant to be the rare case rather than the standing state.
        model = llm.structured_model("classifier", Classification)
        return await model.ainvoke(CLASSIFIER_PROMPT.format(message=message))
    except Exception:
        # The keyword layer has already cleared the blunt cases, so failing open
        # here loses nuance, not the guarantee. Failing closed would take the
        # whole product down whenever the classifier hiccups.
        log.exception("classifier failed, defaulting to OK/SIMPLE")
        return Classification(topic="OK", difficulty="SIMPLE")


def contains_medical(value: str) -> bool:
    """Return True if a string mentions a health condition we must not store."""
    return bool(_MEDICAL_RE.search(value))


def needs_allergen_notice(text: str) -> bool:
    """Return True if a reply named a specific dish or ingredient.

    Counsel's wording is "any response that suggests a specific recipe or
    ingredient", which is narrower than every reply. This was briefly widened to
    always-on because an earlier heuristic missed "Smash burgers. Thin patties,
    screaming hot pan" and a rule that fails on a case that plain cannot gate a
    legal requirement.

    Structured recipes fixed that. The caller now ORs this against the presence
    of a recipe object, which is a reliable signal rather than a guess, so this
    function only has to catch ingredients named in loose prose. That keeps the
    notice off pure conversation, off technique answers that name no food, and
    off "what pan should I buy", where it was only ever noise.

    Still deliberately broad within its scope. A notice shown unnecessarily is a
    line of chrome; one missed is what counsel wrote the email about.
    """
    return bool(_INGREDIENT_RE.search(text))


def looks_like_a_recipe(text: str) -> bool:
    """Whether a reply names measurements, cooking verbs, or common ingredients.

    Kept for the frontend to soften how the notice is presented, never to decide
    whether it appears. See needs_allergen_notice.
    """
    return bool(_INGREDIENT_RE.search(text))
