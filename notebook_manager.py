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
# Persisted snapshot of the in-scope notebook list (shared + allowlisted-own).
# Written by sync_case_studies() so slow memory (get_notebook_list +
# query_specific_notebook) always agrees with fast memory on which notebooks
# the bot may touch, with no per-message network calls.
_SCOPE_PATH = Path(__file__).resolve().parent / "notebook_scope.json"


def _load_notebook_registry() -> list[dict]:
    """Load the hand-curated override list from config.json."""
    try:
        with open(_CONFIG_PATH, "r") as f:
            config = json.load(f)
        return config.get("notebook_projects", [])
    except Exception as exc:
        logger.error("Failed to load config.json: %s", exc)
        return []


def _load_allowed_own_ids() -> set[str]:
    """Own (is_owner=True) notebooks that are explicitly allow-listed for the
    bot. Everything else owned by the account is out of scope."""
    try:
        with open(_CONFIG_PATH, "r") as f:
            config = json.load(f)
        return set(config.get("allowed_own_ids", []) or [])
    except Exception as exc:
        logger.error("Failed to load config.json: %s", exc)
        return set()


def _load_shared_allowed_ids() -> set[str]:
    """The exact shared notebooks the admin has allow-listed. We use this
    instead of the upstream `is_owner=False` flag because that flag
    misclassifies some notebooks (e.g. ones the account shared OUT)."""
    try:
        with open(_CONFIG_PATH, "r") as f:
            config = json.load(f)
        return set(config.get("shared_allowed_ids", []) or [])
    except Exception as exc:
        logger.error("Failed to load config.json: %s", exc)
        return set()


def save_scope(notebooks: list[dict]) -> None:
    """Persist the current in-scope notebook list to disk."""
    _SCOPE_PATH.write_text(json.dumps(notebooks, indent=2))


def load_scope() -> list[dict]:
    """Load the persisted in-scope notebook list. Empty list if missing."""
    if not _SCOPE_PATH.exists():
        return []
    try:
        return json.loads(_SCOPE_PATH.read_text()) or []
    except Exception as exc:
        logger.error("Failed to read notebook_scope.json: %s", exc)
        return []


def is_notebook_in_scope(nb_id: str) -> bool:
    """True iff nb_id is explicitly listed in either shared_allowed_ids or
    allowed_own_ids in config.json. Source of truth, independent of whether
    /sync_memory has populated notebook_scope.json yet."""
    if not nb_id:
        return False
    return nb_id in (_load_shared_allowed_ids() | _load_allowed_own_ids())


def get_notebook_list() -> str:
    """Return a formatted list of in-scope notebooks for the Agent context.

    Read from the on-disk scope file (written by /sync_memory). Falls back
    to config.json `notebook_projects` for the very first run before any
    sync has happened. Always synchronous and cheap — no network calls in
    the user-message hot path.
    """
    scope = load_scope()
    if scope:
        projects = scope
        source_note = ""
    else:
        projects = _load_notebook_registry()
        source_note = (
            "\n(Scope not yet refreshed — run /sync_memory to discover "
            "the latest shared notebooks.)"
        )

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
    return "\n".join(lines) + source_note


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

    if not is_notebook_in_scope(notebook_id):
        logger.warning("Refusing out-of-scope notebook query: %s", notebook_id)
        return (
            "That notebook isn't in my approved scope. I only consult the "
            "case studies shared with our class plus 'The Ecosystem Economy'."
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
    (owned + shared with the user). Includes is_owner so callers can scope.
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
            "is_owner": bool(getattr(nb, "is_owner", True)),
            "created_at": str(nb.created_at) if getattr(nb, "created_at", None) else None,
        }
        for nb in notebooks
    ]


def list_all_notebooks() -> list[dict]:
    """Sync wrapper for `_async_list_all` (call from a worker thread).
    Returns *every* visible notebook — for admin/debug only."""
    return asyncio.run(_async_list_all())


def filter_in_scope(all_nbs: list[dict]) -> list[dict]:
    """Apply the strict allow-list scope: a notebook is in scope iff its ID
    is explicitly listed in either `shared_allowed_ids` or `allowed_own_ids`
    in config.json. The upstream `is_owner` flag is NOT used as a fallback —
    we found it misclassifies some notebooks the account shared outward."""
    allowed = _load_shared_allowed_ids() | _load_allowed_own_ids()
    return [nb for nb in all_nbs if nb.get("id") in allowed]


def list_in_scope_notebooks() -> list[dict]:
    """Sync wrapper: discover + filter to the in-scope subset (the only
    notebooks the bot is allowed to read into fast or slow memory)."""
    all_nbs = list_all_notebooks()
    return filter_in_scope(all_nbs)


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
