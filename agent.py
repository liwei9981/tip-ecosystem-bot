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

# ── Multi-Character System ───────────────────────────────────────────
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

def get_user_character(user_id: int) -> str:
    """Return the current character ID for a user."""
    return _user_characters.get(user_id, "classmate")

async def set_user_character(user_id: int, character_id: str) -> str:
    """Switch the character for a user and generate a dynamic intro."""
    _user_characters[user_id] = character_id
    # Reset conversation when switching characters to avoid context confusion
    _conversations[user_id] = []
    
    # Generate a dynamic introduction instead of using a static string
    return await _generate_dynamic_intro(user_id)

async def _generate_dynamic_intro(user_id: int) -> str:
    """Ask the AI to introduce itself based on the new persona."""
    char_id = _user_characters.get(user_id, "classmate")
    system_prompt = _build_character_prompt(user_id)
    class_context = _load_class_context()
    
    full_prompt = f"{system_prompt}\n\n{SYSTEM_PROMPT_FOOTER.format(class_context=class_context)}"
    
    # Special instruction for the intro
    intro_instruction = (
        "You just joined this study session. Introduce yourself briefly in your unique voice. "
        "Subtly confirm who you are (your role/perspective). "
        "Then, ask the student what they are currently working on regarding the Ecosystem Economy. "
        "CRITICAL: Keep this strictly to 1 or 2 short sentences. Be extremely human, casual, and brief."
    )

    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=intro_instruction)])],
            config=types.GenerateContentConfig(
                system_instruction=full_prompt,
                temperature=0.9, # Higher temperature for more "human" variety
            ),
        )
        intro_text = response.candidates[0].content.parts[0].text
        
        # Add this intro to the conversation history so the bot remembers it
        _conversations[user_id].append(
            types.Content(role="model", parts=[types.Part.from_text(text=intro_text)])
        )
        return intro_text
    except Exception as e:
        logger.error(f"Error generating intro for {char_id}: {e}")
        return "Hey! I'm ready to dive into some ecosystem case studies. What's on your mind?"

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

DIALOGUE EXAMPLES:
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
CRITICAL OPERATIONAL RULES (DO NOT IGNORE):
1. Class Context: {class_context}
2. Broader Intelligence: You are a highly intelligent persona. Feel free to naturally discuss broader life topics, sports, tech, or whatever the user brings up.
3. The Ecosystem Hook (The Art of the Pivot): Do NOT force a transition to the Ecosystem Economy in every single message. Engage in the broader topic naturally for a few rounds. When the moment feels right, or if the conversation stalls, smoothly pivot back to business by dropping a "hook" (a provocative question or recent news about a player like Apple, Disney, Tata). Use your character's attitude when pivoting (e.g., Alex getting impatient with small talk, Beatrice demanding strategic focus, Leo making a nerdy connection).
4. Tool Protocol: Use `search_latest_news` proactively to back up your hooks with current facts.
5. ABSOLUTE LENGTH LIMIT: You MUST keep every response strictly under 3 short sentences. Never write essays, lists, or long paragraphs. 
6. HUMAN RULE: NEVER act like an AI or an assistant. Talk like a real person in a fast-paced chat. Do not summarize. Give your opinion directly.
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

# ── Proactive Hook Generator ───────────────────────────────────────────
async def generate_proactive_hook(user_id: int) -> str:
    """Generate a proactive message if the user has been inactive for 24h."""
    char_id = _user_characters.get(user_id, "classmate")
    system_prompt = _build_character_prompt(user_id)
    class_context = _load_class_context()
    
    full_prompt = f"{system_prompt}\n\n{SYSTEM_PROMPT_FOOTER.format(class_context=class_context)}"
    
    instruction = (
        "SYSTEM TRIGGER: The user has been inactive for 24 hours. "
        "Use `search_latest_news` to find a very recent, real-world update on an ecosystem player we studied (e.g., Apple, Disney, ByteDance, SHEIN, Tata). "
        "Then, send a highly conversational, short (1-2 sentences) message to the user. "
        "Share the news and ask a thought-provoking question to reel them back into the discussion. "
        "Do NOT mention that you are responding to a system trigger. Just act like you just read the news and wanted to share."
    )
    
    config = types.GenerateContentConfig(
        system_instruction=full_prompt,
        tools=ALL_TOOLS,
        temperature=0.9,
    )
    
    # We use a temporary conversation history so the system trigger doesn't pollute the main history
    temp_history = _conversations[user_id].copy()
    temp_history.append(types.Content(role="user", parts=[types.Part.from_text(text=instruction)]))
    
    max_iterations = 3
    for _ in range(max_iterations):
        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=temp_history,
                config=config,
            )
        except Exception as exc:
            logger.error("Gemini API call failed during proactive hook: %s", exc)
            return "Hey! I was just reading up on some case studies. Anything new on your end?"
            
        candidate = response.candidates[0]
        model_content = candidate.content
        temp_history.append(model_content)
        
        function_calls = [part.function_call for part in model_content.parts if part.function_call is not None]
        
        if not function_calls:
            text_parts = [part.text for part in model_content.parts if part.text]
            final_text = "\n".join(text_parts) if text_parts else "Hey! Anything new on your end?"
            
            # Now we add ONLY the final model response to the real history
            _conversations[user_id].append(
                types.Content(role="model", parts=[types.Part.from_text(text=final_text)])
            )
            return final_text
            
        tool_response_parts = []
        for fc in function_calls:
            result_str = _execute_tool_call(fc)
            tool_response_parts.append(
                types.Part.from_function_response(name=fc.name, response={"result": result_str})
            )
        temp_history.append(types.Content(role="tool", parts=tool_response_parts))
        
    return "Hey! I was just reading up on some case studies. Anything new on your end?"

# ── Admin Sync ────────────────────────────────────────────────────────
def trigger_memory_sync() -> str:
    """
    Triggered by the admin to sync new NotebookLM data into the Fast Memory vector DB.
    """
    return sync_case_studies()

