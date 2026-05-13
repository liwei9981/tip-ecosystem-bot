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


def sync_case_studies() -> str:
    """Sync all NotebookLM projects into the local vector DB.

    For each notebook in config.json:
    1. Fetches summary + description via NotebookLM API.
    2. Optionally distills with Gemini for cleaner embeddings.
    3. Stores the result in ChromaDB.

    This is the core mechanism that makes the bot "grow smarter" over time.
    """
    from notebook_manager import _async_get_summary, _async_get_description

    projects = _load_notebook_registry()
    if not projects:
        return "No notebook projects found in config.json."

    collection = _get_collection()
    gemini_key = os.getenv("GEMINI_API_KEY")
    gemini_client = genai.Client(api_key=gemini_key) if gemini_key else None

    synced = 0
    errors = 0
    error_samples: list[str] = []

    for project in projects:
        nb_id = project.get("id", "")
        title = project.get("title", "Untitled")
        week = project.get("week", 0)
        student = project.get("student", "Unknown")
        tags = project.get("tags", [])

        if not nb_id or nb_id == "REPLACE_WITH_NOTEBOOK_ID":
            logger.warning("Skipping unconfigured notebook: %s", title)
            continue

        logger.info("Syncing notebook: %s (week %s)", title, week)

        # Step 1: Get summary + description from NotebookLM
        try:
            summary = asyncio.run(_async_get_summary(nb_id))
            desc = asyncio.run(_async_get_description(nb_id))
            desc_summary = desc.get("summary", "")
            suggested_topics = desc.get("topics", [])

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

        # Step 3: Upsert into ChromaDB
        doc_id = f"week{week}_{nb_id}"
        try:
            collection.upsert(
                ids=[doc_id],
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
            logger.error("ChromaDB upsert failed for %s: %s", title, exc)
            errors += 1

    total_docs = collection.count()
    msg = (
        f"Synced {synced} notebook(s) into Fast Memory "
        f"({errors} error(s)). Total documents in memory: {total_docs}."
    )
    if error_samples:
        msg += "\n\nFirst errors:\n" + "\n".join(f"• {s}" for s in error_samples)
    return msg
