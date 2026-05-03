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
            f"Class: {class_name} (Week {current_week} of {total_weeks})\n"
            f"Available case study notebooks:\n{notebook_list}"
        )
    except Exception:
        return "Class: Ecosystem Economy"


# ── Persona System Prompt ─────────────────────────────────────────────
_PERSONALITY_PATH = Path(__file__).resolve().parent / "personality.md"

def _load_personality() -> str:
    """Read the personality file for the system prompt."""
    try:
        return _PERSONALITY_PATH.read_text(encoding="utf-8")
    except Exception:
        return "You are a curious, younger classmate in an Ecosystem Economy class."

SYSTEM_PROMPT_TEMPLATE = """\
{personality}

---

{class_context}

Tool Usage:
- Use `search_case_study_memory` first for broad questions about class material.
- Use `query_notebook_project` for deep-dive into a specific case study (provide the notebook_id from the list above).
- Use `search_latest_news` when discussing current events or cross-referencing with real-world news.
- If multiple tools are needed, call them one at a time and synthesise the results.
"""


# ── Tool Definitions ──────────────────────────────────────────────────
search_case_study_memory_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_case_study_memory",
            description=(
                "Search the bot's fast-thinking local memory of summarised case "
                "studies from all shared NotebookLM projects. Use this for broad "
                "questions about class material, comparing case studies, or "
                "recalling what classmates have researched."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(
                        type="STRING",
                        description="The search query to look up in the case study memory.",
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
                "Deep-dive into a specific NotebookLM project to get detailed, "
                "specific information. Use this when fast memory isn't enough "
                "and you need the exact data, methodology, or conclusions from "
                "a particular case study. Requires a notebook ID from the "
                "available list."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "notebook_id": types.Schema(
                        type="STRING",
                        description="The ID of the NotebookLM project to query.",
                    ),
                    "query": types.Schema(
                        type="STRING",
                        description="The detailed question to send to the notebook.",
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
                "Search for the latest real-world news articles related to "
                "ecosystem economy topics. Use when discussing current events, "
                "cross-referencing case studies with real-world developments, "
                "or when a student asks about something happening right now."
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
MAX_HISTORY = 20  # Keep last N turns per user
_conversations: dict[int, list[types.Content]] = defaultdict(list)


def _trim_history(user_id: int):
    """Keep conversation history within bounds."""
    history = _conversations[user_id]
    if len(history) > MAX_HISTORY * 2:  # each turn = user + model
        _conversations[user_id] = history[-(MAX_HISTORY * 2):]


def _execute_tool_call(function_call) -> str:
    """Dispatches a tool call from the model to the actual function."""
    name = function_call.name
    args = dict(function_call.args) if function_call.args else {}

    logger.info(f"Tool call: {name}({args})")

    if name == "search_case_study_memory":
        return get_fast_memory_response(args.get("query", ""))
    elif name == "query_notebook_project":
        return query_specific_notebook(
            args.get("notebook_id", ""),
            args.get("query", ""),
        )
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
    """
    Takes a student's message, manages conversation history,
    calls Gemini 3.1 Pro with tool-calling, and returns the response.
    """
    # Add the student's message to history
    _conversations[user_id].append(
        types.Content(role="user", parts=[types.Part.from_text(text=message)])
    )
    _trim_history(user_id)

    # Build the system prompt with personality + dynamic class context
    personality = _load_personality()
    class_context = _load_class_context()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        personality=personality,
        class_context=class_context,
    )

    # Build the config with system instruction and tools
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=ALL_TOOLS,
        temperature=0.8,
        max_output_tokens=2048,
    )

    # Agentic loop: model may request tool calls iteratively
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
            # Remove the failed message from history to avoid poisoning
            if _conversations[user_id]:
                _conversations[user_id].pop()
            return f"Oops, my brain just froze for a second 🥶 Could you try saying that again?"

        candidate = response.candidates[0]
        model_content = candidate.content

        # Save the model's response (which may contain tool calls or text)
        _conversations[user_id].append(model_content)

        # Check if the model wants to call a tool
        function_calls = [
            part.function_call
            for part in model_content.parts
            if part.function_call is not None
        ]

        if not function_calls:
            # No tool calls — return the text response
            text_parts = [
                part.text for part in model_content.parts if part.text
            ]
            return "\n".join(text_parts) if text_parts else "Hmm, I'm not sure what to say about that. Could you rephrase? 🤔"

        # Execute each tool call and feed results back
        tool_response_parts = []
        for fc in function_calls:
            # Notify the bot which tool we're starting
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

        # Add tool responses to history
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
