"""Tools the model may call.

Nothing here is sequenced. The model reads these descriptions and decides on its
own whether a tool is worth calling, which is the LLM-driven tool use the brief
requires. That makes the docstrings load-bearing: they are the only instruction
the model gets about when to reach for a tool.
"""

import logging

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_tavily import TavilySearch

from app import profile as user_profile
from app.config import get_settings
from app.schemas import Recipe

log = logging.getLogger(__name__)

# Three is enough to answer a cooking question and few enough that the results
# do not crowd out the conversation in the model's context.
MAX_RESULTS = 3


@tool(response_format="content_and_artifact")
async def search_web(query: str) -> tuple[str, list[dict]]:
    """Look up cooking information on the web that you do not already know well.

    Reach for this when the answer depends on something you cannot state
    confidently from memory: an unfamiliar ingredient or cuisine, a specific
    product or brand, a regional dish you only half know, current prices or
    availability, or a technique where being wrong would waste the user's food.

    Do not use it for ordinary cooking knowledge you already have. Searching
    costs the user several seconds, so a confident answer beats a researched one
    when you are already sure.

    Args:
        query: A short search phrase, not a full sentence.
    """
    settings = get_settings()
    if not settings.tavily_api_key:
        # Missing key is a config problem, not a user problem. Tell the model
        # plainly so it answers from its own knowledge instead of stalling.
        log.warning("search called with no Tavily key configured")
        return "Search is unavailable. Answer from your own knowledge.", []

    try:
        results = await TavilySearch(max_results=MAX_RESULTS).ainvoke({"query": query})
    except Exception:
        # A search outage must not take the conversation down with it. The model
        # sees a plain note and carries on unaided.
        log.exception("web search failed")
        return "Search failed. Answer from your own knowledge.", []

    items = results.get("results", []) if isinstance(results, dict) else []
    if not items:
        return "No results found.", []

    # Two shapes from one call: readable text for the model, and structured
    # sources for the UI. The artifact rides along on the ToolMessage so the
    # graph can collect it without parsing the text back apart.
    text = "\n\n".join(
        f"{item.get('title', 'Untitled')}\n{item.get('content', '')}" for item in items
    )
    sources = [
        {"title": item.get("title") or item.get("url", "Source"), "url": item.get("url", "")}
        for item in items
        if item.get("url")
    ]
    return text, sources


def _user_id(config: RunnableConfig) -> str:
    """Pull the caller's id out of the run config, never out of the model's args."""
    # Injected by the graph, invisible to the model. If the model could pass a
    # user id it could read or overwrite someone else's profile by guessing one.
    return (config or {}).get("configurable", {}).get("user_id", "")


@tool
async def get_user_profile(config: RunnableConfig) -> str:
    """Look up what you already know about this user before you answer.

    Worth calling whenever what to suggest depends on them: what equipment they
    have, what they like, what they will not eat. Check before assuming their
    kitchen is empty, and before assuming it is well stocked.
    """
    profile = await user_profile.get_profile(_user_id(config))
    rendered = user_profile.profile_to_prompt(profile)
    return rendered or "Nothing stored about this user yet."


@tool
async def remember_about_user(
    config: RunnableConfig,
    cookware: list[str] | None = None,
    likes: list[str] | None = None,
    dislikes: list[str] | None = None,
    avoid: list[str] | None = None,
) -> str:
    """Save something durable a user told you about themselves. Call this often.

    Call it the moment they mention equipment they own or lack, a cuisine or
    flavour they love, something they will not eat, or an ingredient to keep
    away from them. Call it in the same turn you heard the fact and before you
    answer them, because nothing you do not save survives to the next session.

    Examples that must each trigger a call:
        "I only have a hot plate and one pan" -> cookware=["hot plate", "one pan"]
        "I'm vegetarian"                      -> likes=["vegetarian"]
        "I can't stand coriander"             -> dislikes=["coriander"]
        "I'm allergic to shellfish"           -> avoid=["shellfish"]

    Saving is silent. Call the tool, then answer as though you simply knew.

    Never call this with a health condition, a diagnosis, a medication, or a
    pregnancy. Those are not preferences and must not be stored anywhere.

    Args:
        cookware: Equipment they own, e.g. ["air fryer", "cast iron pan"].
        likes: Cuisines or flavours they enjoy, e.g. ["thai", "very spicy"].
        dislikes: Food they would rather not eat, e.g. ["coriander"].
        avoid: Ingredients never to suggest, e.g. ["shellfish"]. Use this for
            allergies, recording only the ingredient itself and nothing about why.
    """
    user_id = _user_id(config)
    if not user_id:
        log.warning("remember_about_user called with no user id in config")
        return "Could not save that."

    await user_profile.save_profile(
        user_id, cookware=cookware, likes=likes, dislikes=dislikes, avoid=avoid
    )
    # Deliberately terse. A chatty confirmation tempts the model into telling
    # the user it took notes, which the persona forbids.
    return "Saved."


# One entry is an instruction or an ingredient line, not a paragraph. Past these
# the model is writing an essay into the card, which the layout cannot show.
MAX_LINE_CHARS = 400
MAX_LINES = 40


def _clean_lines(values: list[str] | None) -> list[str]:
    """Normalize a list of recipe lines, dropping blanks and absurd lengths."""
    out: list[str] = []
    for raw in values or []:
        line = " ".join(str(raw).split()).strip()
        if line and len(line) <= MAX_LINE_CHARS:
            out.append(line)
    return out[:MAX_LINES]


def _bounded(value, low: int, high: int) -> int | None:
    """Coerce a model-supplied number into range, or None if it will not fit.

    Dropping one bad field beats losing the card. A model that answers "about 30"
    or serves=0 has still given a recipe worth showing, and the frontend already
    renders a missing number as a blank slot rather than a broken one.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


@tool(response_format="content_and_artifact")
async def present_recipe(
    title: str,
    steps: list[str],
    ingredients: list[str] | None = None,
    time_mins: int | None = None,
    difficulty: str | None = None,
    serves: int | None = None,
) -> tuple[str, dict | None]:
    """Show a recipe card when you are recommending one specific dish to cook.

    Call this the moment you have settled on a dish and are about to describe how
    to make it. The card is what the user cooks from: it stays on screen, and
    they can save it.

    Keep talking normally as well. The card is not your answer — you are. Say why
    this dish, what to watch for, what you would do differently; the card just
    carries the numbered version so they are not scrolling back through chat with
    wet hands. A turn that is only a card reads like a search result.

    Do not call this for a question that has no single dish behind it, for
    general technique, or for a list of options you are floating.

    Leave a field out when you do not know it. An omitted time is honest; a
    guessed one sends someone to the shops on bad information.

    Args:
        title: What the dish is called, e.g. "Carbonara".
        steps: The method, one instruction per entry, in order.
        ingredients: What they need, one per entry, with quantities if you have
            them, e.g. ["200g spaghetti", "2 egg yolks"].
        time_mins: Total time in minutes, start to plate.
        difficulty: Exactly one of "easy", "medium", or "hard".
        serves: How many people it feeds.
    """
    name = " ".join(str(title or "").split())[:200]
    if not name:
        # A card with no title has nothing to render and nothing to save under.
        # The model is told plainly so it answers in prose rather than stalls.
        log.warning("present_recipe called without a title")
        return "Could not show that card. Answer in prose instead.", None

    grade = str(difficulty or "").strip().lower()
    recipe = Recipe(
        title=name,
        steps=_clean_lines(steps),
        ingredients=_clean_lines(ingredients),
        time_mins=_bounded(time_mins, 1, 6000),
        # Anything the model invents beyond the three words is dropped rather
        # than raised, on the same reasoning as _bounded.
        difficulty=grade if grade in ("easy", "medium", "hard") else None,
        serves=_bounded(serves, 1, 100),
    )
    # Terse for the same reason remember_about_user is: a chatty confirmation
    # tempts the model into announcing the card, which the user can already see.
    return "Recipe card shown.", recipe.model_dump()


# Registered in one place so the graph and any future caller bind the same set.
ALL_TOOLS = [search_web, get_user_profile, remember_about_user, present_recipe]
