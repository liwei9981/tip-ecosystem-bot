"""Core Memory Manager — "Fast Thinking" with ChromaDB.

Manages the local vector database of summarised NotebookLM content.
The bot's "brain" grows as the admin syncs new case studies each week.

Sync is triggered manually by the admin via `/sync_memory` in Telegram.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path

import chromadb
from google import genai
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_DB_DIR = Path(__file__).resolve().parent / "chroma_db"
_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
_COLLECTION_NAME = "ecosystem_case_studies"


def _get_client() -> chromadb.PersistentClient:
    """Return a persistent ChromaDB client."""
    _DB_DIR.mkdir(exist_ok=True)
    return chromadb.PersistentClient(path=str(_DB_DIR))


def _get_collection() -> chromadb.Collection:
    """Get or create the case-studies collection."""
    client = _get_client()
    return client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _load_notebook_registry() -> list[dict]:
    """Load the list of NotebookLM projects from config.json."""
    try:
        with open(_CONFIG_PATH, "r") as f:
            config = json.load(f)
        return config.get("notebook_projects", [])
    except Exception as exc:
        logger.error("Failed to load config.json: %s", exc)
        return []


def get_fast_memory_response(query: str) -> str:
    """Query the local vector DB for relevant case study summaries.

    Returns a synthesised text block from the top matching documents.
    If the DB is empty, returns a helpful message.
    """
    try:
        collection = _get_collection()

        if collection.count() == 0:
            return (
                "I haven't loaded any case studies into my memory yet. "
                "The admin needs to run /sync_memory first so I can start "
                "learning from the shared NotebookLM projects!"
            )

        results = collection.query(
            query_texts=[query],
            n_results=min(5, collection.count()),
        )

        if not results or not results.get("documents"):
            return "I couldn't find anything directly relevant in my memory about that."

        # Build context from the top matches
        docs = results["documents"][0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        parts: list[str] = []
        for i, (doc, meta, dist) in enumerate(zip(docs, metadatas, distances)):
            title = meta.get("title", "Unknown Case Study") if meta else "Unknown"
            week = meta.get("week", "?") if meta else "?"
            student = meta.get("student", "a classmate") if meta else "a classmate"
            similarity = 1 - dist  # cosine distance → similarity

            parts.append(
                f"[Week {week} — {title} by {student} "
                f"(relevance: {similarity:.0%})]\n{doc}"
            )

        return "\n\n---\n\n".join(parts)

    except Exception as exc:
        logger.error("Fast memory query failed: %s", exc)
        return f"My memory search hit an error: {exc}"


def get_all_memory() -> list[dict]:
    """Return every document currently stored in the fast-memory collection,
    along with its metadata. Used by the /show_memory admin command so the
    operator can verify what the bot actually 'knows'.
    """
    collection = _get_collection()
    if collection.count() == 0:
        return []
    results = collection.get(include=["documents", "metadatas"])
    ids = results.get("ids", []) or []
    docs = results.get("documents", []) or []
    metas = results.get("metadatas", []) or []
    items = [
        {"id": id_, "metadata": meta or {}, "document": doc or ""}
        for id_, meta, doc in zip(ids, metas, docs)
    ]
    items.sort(key=lambda x: (str(x["metadata"].get("week", "")), x["metadata"].get("title", "")))
    return items


_WEEK_RE = re.compile(r"(?:Session|Section)\s*(\d+)", re.IGNORECASE)


def _derive_meta_from_title(title: str) -> tuple[str, str]:
    """Best-effort parse of (week, student) from a NotebookLM title like
    'Session 9 - NextGen Synergies - Disney - Adi'.
    Returns ('', '') when the pattern doesn't match.
    """
    if not title:
        return "", ""
    week_match = _WEEK_RE.search(title)
    week = week_match.group(1) if week_match else ""
    parts = [p.strip() for p in title.split(" - ") if p.strip()]
    student = parts[-1] if len(parts) >= 2 else ""
    return week, student


def sync_case_studies(force: bool = False) -> str:
    """Incrementally sync all NotebookLM projects visible to the bot's account
    into the local vector DB.

    Strategy:
    - Discover every notebook via nlm.notebooks.list() (owned + shared).
    - Use the notebook_id as the ChromaDB document ID so existing entries are
      detected and skipped — only new notebooks are fetched & embedded.
    - config.json acts as an optional override map for week/student/tags;
      missing metadata is derived from the title.
    - Pass force=True to re-sync everything (e.g. after a notebook's contents
      have changed upstream).
    """
    from notebook_manager import (
        _async_get_summary,
        _async_get_description,
        list_in_scope_notebooks,
        save_scope,
    )

    try:
        visible = list_in_scope_notebooks()
    except Exception as exc:
        logger.error("Failed to list NotebookLM projects: %s", exc, exc_info=True)
        return f"Couldn't list NotebookLM projects: {type(exc).__name__}: {exc}"

    if not visible:
        return (
            "No in-scope NotebookLM projects found. Scope = shared notebooks "
            "+ allowed_own_ids in config.json."
        )

    # Persist the scope so slow memory (get_notebook_list /
    # query_specific_notebook) stays aligned with the fast-memory contents.
    # Enrich with override metadata from config.json before persisting.
    overrides_for_save = {p["id"]: p for p in _load_notebook_registry() if p.get("id")}
    enriched_scope = []
    for nb in visible:
        ov = overrides_for_save.get(nb["id"], {})
        d_week, d_student = _derive_meta_from_title(nb.get("title", ""))
        enriched_scope.append({
            "id": nb["id"],
            "title": ov.get("title") or nb.get("title") or "Untitled",
            "week": ov.get("week") or d_week or "?",
            "student": ov.get("student") or d_student or "Unknown",
            "tags": ov.get("tags", []),
            "is_owner": nb.get("is_owner", True),
            "sources_count": nb.get("sources_count", 0),
        })
    save_scope(enriched_scope)

    overrides = {p["id"]: p for p in _load_notebook_registry() if p.get("id")}

    collection = _get_collection()

    # Build the set of notebook_ids already represented in the DB. Tolerate
    # legacy IDs that were stored as `week{N}_{nb_id}` before this refactor.
    existing_ids = set(collection.get().get("ids", []) or [])
    covered_nb_ids: set[str] = set()
    legacy_by_nb: dict[str, list[str]] = {}
    for doc_id in existing_ids:
        nb_part = doc_id.split("_", 1)[1] if "_" in doc_id else doc_id
        covered_nb_ids.add(nb_part)
        if doc_id != nb_part:
            legacy_by_nb.setdefault(nb_part, []).append(doc_id)

    gemini_key = os.getenv("GEMINI_API_KEY")
    gemini_client = genai.Client(api_key=gemini_key) if gemini_key else None

    synced = 0
    skipped = 0
    errors = 0
    error_samples: list[str] = []

    for nb in visible:
        nb_id = nb.get("id") or ""
        if not nb_id:
            continue

        if not force and nb_id in covered_nb_ids:
            skipped += 1
            continue

        override = overrides.get(nb_id, {})
        title = override.get("title") or nb.get("title") or "Untitled"
        derived_week, derived_student = _derive_meta_from_title(title)
        week = override.get("week") or derived_week or "?"
        student = override.get("student") or derived_student or "Unknown"
        tags = override.get("tags", [])

        logger.info("Syncing notebook: %s (week %s)", title, week)

        # Step 1: Get summary + description from NotebookLM
        try:
            summary = asyncio.run(_async_get_summary(nb_id))
            desc = asyncio.run(_async_get_description(nb_id))
            desc_summary = desc.get("summary", "")
            suggested_topics = desc.get("topics", [])

            # The inner helpers swallow their own exceptions and return empty
            # values, so an empty fetch is the actual signal that something
            # failed (auth, network, Playwright, etc.).
            if not summary and not desc_summary and not suggested_topics:
                raise RuntimeError(
                    "NotebookLM returned no summary/description/topics "
                    "(likely auth expired, network, or Playwright failure — "
                    "check docker logs)"
                )

            # Combine summary + description for richer content
            raw_content = f"Summary: {summary}\n\n"
            if desc_summary:
                raw_content += f"Description: {desc_summary}\n\n"
            if suggested_topics:
                topics_text = "\n".join(
                    f"- {t['question']}" for t in suggested_topics
                )
                raw_content += f"Key Questions:\n{topics_text}"

        except Exception as exc:
            logger.error("Failed to fetch notebook %s: %s", nb_id, exc, exc_info=True)
            errors += 1
            if len(error_samples) < 2:
                error_samples.append(f"{title}: {type(exc).__name__}: {exc}")
            continue

        # Step 2: Optionally distill with Gemini for cleaner embeddings
        if gemini_client and raw_content:
            try:
                distill_response = gemini_client.models.generate_content(
                    model="gemini-3-flash-preview",
                    contents=(
                        f"Distill the following case study content into a concise, "
                        f"information-dense paragraph (200-400 words) that captures "
                        f"the key themes, findings, and unique insights. This will be "
                        f"used for semantic search, so include specific terminology "
                        f"and concepts.\n\n"
                        f"Case Study: {title}\n"
                        f"Student: {student}\n"
                        f"Week: {week}\n\n"
                        f"Content:\n{raw_content}"
                    ),
                )
                distilled = distill_response.text.strip()
            except Exception as exc:
                logger.warning("Gemini distillation failed, using raw: %s", exc)
                distilled = raw_content
        else:
            distilled = raw_content

        # Step 3: Upsert into ChromaDB using notebook_id as the stable doc id
        try:
            stale = legacy_by_nb.get(nb_id, [])
            if stale:
                collection.delete(ids=stale)
            collection.upsert(
                ids=[nb_id],
                documents=[distilled],
                metadatas=[{
                    "title": title,
                    "week": str(week),
                    "student": student,
                    "notebook_id": nb_id,
                    "tags": ",".join(tags),
                }],
            )
            synced += 1
            logger.info("✅ Synced: %s", title)
        except Exception as exc:
            logger.error("ChromaDB upsert failed for %s: %s", title, exc, exc_info=True)
            errors += 1
            if len(error_samples) < 2:
                error_samples.append(
                    f"{title} [upsert]: {type(exc).__name__}: {exc}"
                )

    total_docs = collection.count()
    mode = "force-resync" if force else "incremental"
    msg = (
        f"[{mode}] Synced {synced} new notebook(s), skipped {skipped} "
        f"already in memory, {errors} error(s). "
        f"Total visible: {len(visible)}. Total in memory: {total_docs}."
    )
    if error_samples:
        msg += "\n\nFirst errors:\n" + "\n".join(f"• {s}" for s in error_samples)
    return msg
