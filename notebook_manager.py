"""NotebookLM Connector — "Slow Thinking" tool.

Provides targeted, deep-dive queries into specific NotebookLM projects
using the `nlm.chat.ask()` API for interactive Q&A, and
`nlm.notebooks.get_summary()` / `nlm.notebooks.get_description()` for
bulk summarisation during memory sync.

Authentication uses browser-cookie-based sessions via `notebooklm-py`.
Run `notebooklm login` once before first use.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from notebooklm import NotebookLMClient

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def _load_notebook_registry() -> list[dict]:
    """Load the list of NotebookLM projects from config.json."""
    try:
        with open(_CONFIG_PATH, "r") as f:
            config = json.load(f)
        return config.get("notebook_projects", [])
    except Exception as exc:
        logger.error("Failed to load config.json: %s", exc)
        return []


def get_notebook_list() -> str:
    """Return a formatted list of available notebooks for the Agent context."""
    projects = _load_notebook_registry()
    if not projects:
        return "No NotebookLM projects configured yet."

    lines = []
    for p in projects:
        tags = ", ".join(p.get("tags", []))
        lines.append(
            f"- ID: {p['id']} | Week {p.get('week', '?')}: "
            f"{p.get('title', 'Untitled')} (by {p.get('student', 'Unknown')}) "
            f"[{tags}]"
        )
    return "\n".join(lines)


def query_specific_notebook(notebook_id: str, query: str) -> str:
    """Slow Thinking tool — query a specific NotebookLM project.

    Uses nlm.chat.ask() to send a question to the notebook and get
    a detailed, source-grounded response.
    """
    if not notebook_id or notebook_id == "REPLACE_WITH_NOTEBOOK_ID":
        return (
            "This notebook ID hasn't been configured yet. "
            "Ask the admin to update config.json with the real NotebookLM project IDs."
        )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context — run in a thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _async_query_notebook(notebook_id, query))
                return future.result(timeout=120)
        else:
            return asyncio.run(_async_query_notebook(notebook_id, query))
    except RuntimeError:
        return asyncio.run(_async_query_notebook(notebook_id, query))
    except Exception as exc:
        logger.error("NotebookLM query failed for %s: %s", notebook_id, exc)
        return f"I tried to look deeper into this case study but ran into an issue: {exc}"


async def _async_query_notebook(notebook_id: str, query: str) -> str:
    """Async implementation: use nlm.chat.ask() for interactive Q&A."""
    logger.info("Slow Thinking: querying notebook %s with: %s", notebook_id, query[:80])

    client = await NotebookLMClient.from_storage()
    async with client as nlm:
        try:
            result = await nlm.chat.ask(notebook_id, query)
            answer = result.answer if hasattr(result, 'answer') else str(result)
            logger.info("Slow Thinking response received (%d chars)", len(answer))
            return answer
        except Exception as exc:
            logger.error("chat.ask() failed: %s", exc)
            return f"Could not query this notebook: {exc}"


async def _async_get_summary(notebook_id: str) -> str:
    """Get the summary of a notebook for Fast Memory sync."""
    logger.info("Fetching summary for notebook %s", notebook_id)

    client = await NotebookLMClient.from_storage()
    async with client as nlm:
        try:
            summary = await nlm.notebooks.get_summary(notebook_id)
            return summary if isinstance(summary, str) else str(summary)
        except Exception as exc:
            logger.error("get_summary() failed for %s: %s", notebook_id, exc)
            return ""


async def _async_list_all() -> list[dict]:
    """Enumerate every NotebookLM project visible to the authenticated account
    (owned + shared with the user).
    """
    logger.info("Listing all NotebookLM projects")
    client = await NotebookLMClient.from_storage()
    async with client as nlm:
        notebooks = await nlm.notebooks.list()
    return [
        {
            "id": nb.id,
            "title": nb.title,
            "sources_count": getattr(nb, "sources_count", 0),
            "created_at": str(nb.created_at) if getattr(nb, "created_at", None) else None,
        }
        for nb in notebooks
    ]


def list_all_notebooks() -> list[dict]:
    """Sync wrapper for `_async_list_all` (call from a worker thread)."""
    return asyncio.run(_async_list_all())


async def _async_get_description(notebook_id: str) -> dict:
    """Get the rich description of a notebook (summary + suggested topics)."""
    logger.info("Fetching description for notebook %s", notebook_id)

    client = await NotebookLMClient.from_storage()
    async with client as nlm:
        try:
            desc = await nlm.notebooks.get_description(notebook_id)
            return {
                "summary": desc.summary if hasattr(desc, 'summary') else str(desc),
                "topics": [
                    {"question": t.question, "prompt": t.prompt}
                    for t in (desc.suggested_topics if hasattr(desc, 'suggested_topics') else [])
                ],
            }
        except Exception as exc:
            logger.error("get_description() failed for %s: %s", notebook_id, exc)
            return {"summary": "", "topics": []}
