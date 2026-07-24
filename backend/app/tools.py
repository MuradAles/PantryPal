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


# Registered in one place so the graph and any future caller bind the same set.
ALL_TOOLS = [search_web, get_user_profile, remember_about_user]
