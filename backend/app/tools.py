"""Tools the model may call.

Nothing here is sequenced. The model reads these descriptions and decides on its
own whether a tool is worth calling, which is the LLM-driven tool use the brief
requires. That makes the docstrings load-bearing: they are the only instruction
the model gets about when to reach for a tool.
"""

import logging

from langchain_core.tools import tool
from langchain_tavily import TavilySearch

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


# Registered in one place so the graph and any future caller bind the same set.
ALL_TOOLS = [search_web]
