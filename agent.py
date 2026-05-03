"""Orchestrator / Agent — powered by Gemini 3.1 Pro.

Implements the "Curious Classmate" persona with a Dual-System Cognitive
Architecture (Fast & Slow Thinking) using native Gemini tool-calling.
"""

from __future__ import annotations

import os
import json
import logging
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from memory_manager import get_fast_memory_response, sync_case_studies
from notebook_manager import query_specific_notebook, get_notebook_list
from news_fetcher import search_latest_news

load_dotenv()
logger = logging.getLogger(__name__)

# ── Gemini 3.1 Pro Client ─────────────────────────────────────────────
MODEL_ID = "gemini-3.1-pro-preview"

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ── Load class config for context ─────────────────────────────────────
_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

def _load_class_context() -> str:
    """Build a dynamic context block from config.json."""
    try:
        with open(_CONFIG_PATH, "r") as f:
            config = json.load(f)
        class_name = config.get("class_name", "Ecosystem Economy")
        current_week = config.get("current_week", 1)
        total_weeks = config.get("total_weeks", 6)
        notebook_list = get_notebook_list()
        return (
            f"Class: {class_name} (Week {c# ── Multi-Character System ───────────────────────────────────────────
_CHARACTERS_DIR = Path(__file__).resolve().parent / "characters"
_user_characters: dict[int, str] = {}  # user_id -> character_id (e.g. 'classmate')

def get_available_characters() -> dict[str, str]:
    """Return a map of character_id -> character_name."""
    chars = {}
    if not _CHARACTERS_DIR.exists():
        return {"classmate": "The Curious Classmate"}
    for f in _CHARACTERS_DIR.glob("*.json"):
        try:
            with open(f, "r") as j:
                data = json.load(j)
                chars[f.stem] = data.get("name", f.stem)
        except Exception:
            continue
    return chars

def set_user_character(user_id: int, character_id: str) -> str:
    """Switch the character for a user and return the first message."""
    _user_characters[user_id] = character_id
    # Reset conversation when switching characters to avoid context confusion
    _conversations[user_id] = []
    
    char_path = _CHARACTERS_DIR / f"{character_id}.json"
    if char_path.exists():
        with open(char_path, "r") as f:
            data = json.load(f)
            return data.get("first_mes", f"Switched to {character_id}!")
    return f"Switched to {character_id}!"

def _build_character_prompt(user_id: int) -> str:
    """Construct a high-fidelity system prompt from the character JSON."""
    char_id = _user_characters.get(user_id, "classmate")
    char_path = _CHARACTERS_DIR / f"{char_id}.json"
    
    # Fallback to legacy personality.md if no JSON exists
    if not char_path.exists():
        return _load_personality()

    try:
        with open(char_path, "r") as f:
            c = json.load(f)
        
        prompt = f"""\
You are {c.get('name')}.

DESCRIPTION:
{c.get('description')}

PERSONALITY:
{c.get('personality')}

SCENARIO:
{c.get('scenario')}

DIALOUGE EXAMPLES:
{c.get('mes_example')}

CORE INSTRUCTIONS:
{c.get('system_prompt')}
"""
        return prompt
    except Exception as e:
        logger.error(f"Error loading character {char_id}: {e}")
        return _load_personality()

SYSTEM_PROMPT_FOOTER = """
---

{class_context}

Tool Usage:
- Use `search_case_study_memory` first for broad questions about class material.
- Use `query_notebook_project` for deep-dive into a specific case study.
- Use `search_latest_news` for real-world cross-referencing.
"""


# ── Tool Definitions ──────────────────────────────────────────────────
# (No changes to tools)
search_case_study_memory_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_case_study_memory",
            description=(
                "Search the bot's fast-thinking local memory of summarised case "
                "studies from all shared NotebookLM projects."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(
                        type="STRING",
                        description="The search query.",
                    ),
                },
                required=["query"],
            ),
        )
    ]
)

query_notebook_project_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="query_notebook_project",
            description=(
                "Deep-dive into a specific NotebookLM project for details."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "notebook_id": types.Schema(
                        type="STRING",
                        description="The ID of the NotebookLM project.",
                    ),
                    "query": types.Schema(
                        type="STRING",
                        description="The question to send.",
                    ),
                },
                required=["notebook_id", "query"],
            ),
        )
    ]
)

search_latest_news_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_latest_news",
            description=(
                "Search for real-world news articles."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(
                        type="STRING",
                        description="The news search query.",
                    ),
                },
                required=["query"],
            ),
        )
    ]
)

ALL_TOOLS = [
    search_case_study_memory_tool,
    query_notebook_project_tool,
    search_latest_news_tool,
]

# ── Conversation History (per user, in-memory) ────────────────────────
MAX_HISTORY = 20
_conversations: dict[int, list[types.Content]] = defaultdict(list)

def _trim_history(user_id: int):
    history = _conversations[user_id]
    if len(history) > MAX_HISTORY * 2:
        _conversations[user_id] = history[-(MAX_HISTORY * 2):]

def _execute_tool_call(function_call) -> str:
    name = function_call.name
    args = dict(function_call.args) if function_call.args else {}
    logger.info(f"Tool call: {name}({args})")
    if name == "search_case_study_memory":
        return get_fast_memory_response(args.get("query", ""))
    elif name == "query_notebook_project":
        return query_specific_notebook(args.get("notebook_id", ""), args.get("query", ""))
    elif name == "search_latest_news":
        return search_latest_news(args.get("query", ""))
    else:
        return f"Unknown tool: {name}"

# ── Main Orchestrator ─────────────────────────────────────────────────
async def process_student_message(
    user_id: int, 
    message: str, 
    on_slow_tool_start: callable = None
) -> str:
    # Add the student's message to history
    _conversations[user_id].append(
        types.Content(role="user", parts=[types.Part.from_text(text=message)])
    )
    _trim_history(user_id)

    # Build character-specific prompt
    personality_block = _build_character_prompt(user_id)
    class_context = _load_class_context()
    
    system_prompt = f"{personality_block}\n{SYSTEM_PROMPT_FOOTER.format(class_context=class_context)}"

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=ALL_TOOLS,
        temperature=0.8,
        max_output_tokens=2048,
    )

    max_iterations = 5
    slow_tool_triggered = False

    for _ in range(max_iterations):
        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=_conversations[user_id],
                config=config,
            )
        except Exception as exc:
            logger.error("Gemini API call failed: %s", exc)
            if _conversations[user_id]:
                _conversations[user_id].pop()
            return f"Oops, my brain just froze for a second 🥶 Could you try saying that again?"

        candidate = response.candidates[0]
        model_content = candidate.content
        _conversations[user_id].append(model_content)

        function_calls = [
            part.function_call
            for part in model_content.parts
            if part.function_call is not None
        ]

        if not function_calls:
            text_parts = [part.text for part in model_content.parts if part.text]
            return "\n".join(text_parts) if text_parts else "Hmm..."

        tool_response_parts = []
        for fc in function_calls:
            if on_slow_tool_start and not slow_tool_triggered:
                await on_slow_tool_start(fc.name)
                slow_tool_triggered = True

            result_str = _execute_tool_call(fc)
            tool_response_parts.append(
                types.Part.from_function_response(
                    name=fc.name,
                    response={"result": result_str},
                )
            )

        _conversations[user_id].append(
            types.Content(role="tool", parts=tool_response_parts)
        )

    return "Wow, I went down a rabbit hole there! Could you ask me again in a simpler way? 😅"

# ── Admin Sync ────────────────────────────────────────────────────────
def trigger_memory_sync() -> str:
    """
    Triggered by the admin to sync new NotebookLM data into the Fast Memory vector DB.
    """
    return sync_case_studies()

