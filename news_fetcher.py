"""News fetcher using Tavily Search API.

Provides real-time news search for the Agent's "News Awareness" tool.
Adapted from 11_NotebookLM learning Bot/news_fetcher.py.
"""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()
logger = logging.getLogger(__name__)


def search_latest_news(query: str, max_results: int = 5) -> str:
    """Search for the latest news articles related to a query.

    Returns a formatted string of results suitable for injection into
    the LLM context.  Runs synchronously (the Agent calls it from the
    agentic loop which is already in an async context via asyncio.to_thread
    if needed — but since Gemini's generate_content is sync, this is fine).
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key or api_key == "your_tavily_api_key_here":
        return (
            "News search is not configured yet — the TAVILY_API_KEY "
            "environment variable is missing."
        )

    # Append "ecosystem economy" context to improve relevance
    enriched_query = f"{query} ecosystem economy"

    try:
        tavily = TavilyClient(api_key=api_key)
        response = tavily.search(
            query=enriched_query,
            search_depth="basic",
            topic="news",
            days=7,
            max_results=max_results,
        )
        results = response.get("results", [])
    except Exception as exc:
        logger.error("Tavily search failed for '%s': %s", query, exc)
        return f"Sorry, the news search failed: {exc}"

    if not results:
        return f"No recent news found for: {query}"

    # Format into a readable block
    parts: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        snippet = r.get("content", r.get("snippet", ""))[:300]
        date = r.get("published_date", "")
        date_str = f" ({date})" if date else ""

        parts.append(
            f"{i}. {title}{date_str}\n"
            f"   {snippet}\n"
            f"   Source: {url}"
        )

    return "\n\n".join(parts)
