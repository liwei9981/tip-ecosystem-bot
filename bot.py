#!/usr/bin/env python3
"""Ecosystem Economy — Curious Classmate Telegram Bot.

Commands
--------
/start        – Welcome message & introduce the bot
/sync_memory  – (Admin only) Trigger Fast Memory sync from NotebookLM
/reset        – Reset conversation history
"""

from __future__ import annotations

import os
import logging

from dotenv import load_dotenv
from telegram import Update, BotCommand, MenuButtonCommands, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

from agent import (
    process_student_message, 
    trigger_memory_sync, 
    get_available_characters, 
    set_user_character,
    get_user_character
)

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

load_dotenv()


# ════════════════════════════════════════════════════════════════════════
#  Typing indicator helper
# ════════════════════════════════════════════════════════════════════════
# Telegram's `typing…` action lasts ~5 seconds before clients clear it.
# Mobile clients are forgiving, but Telegram Web drops the indicator
# noticeably sooner — so we refresh every 3 seconds to keep it visible
# on all clients uniformly.
_TYPING_REFRESH_SECONDS = 3


def start_typing_loop(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Start a background task that keeps the `typing…` indicator alive.
    Returns the asyncio.Task — cancel it when the reply is ready.
    """
    import asyncio

    async def _loop():
        try:
            while True:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(_TYPING_REFRESH_SECONDS)
        except asyncio.CancelledError:
            pass

    return asyncio.create_task(_loop())


# ════════════════════════════════════════════════════════════════════════
#  Command handlers
# ════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start — introduce the classmate and characters."""
    user = update.effective_user
    name = user.first_name if user else "there"
    
    welcome_text = (
        f"Hey {name}! 👋\n\n"
        "I'm Teddy! Welcome to our Ecosystem Economy study group. "
        "I can take on different perspectives to help you deconstruct the case studies.\n\n"
        "Please pick which 'Teddy' you want to talk to today:"
    )
    
    await show_character_menu(update, welcome_text)


async def cmd_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to switch characters manually."""
    await show_character_menu(update, "Select my perspective:")


async def show_character_menu(update: Update, text: str = "Select my perspective:"):
    """Helper to show a simple, concise character selection keyboard."""
    chars = get_available_characters()
    
    # Very brief descriptions all named Teddy
    labels = {
        "classmate": "Teddy 🧑‍🎓 (Curious Student)",
        "vc": "Teddy 🦈 (Skeptical VC)",
        "consultant": "Teddy 📊 (Strategic Advisor)"
    }
    
    keyboard = []
    for char_id, char_name in chars.items():
        btn_text = labels.get(char_id, f"Teddy ({char_name})")
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"char_{char_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.effective_chat.send_message(text, reply_markup=reply_markup, parse_mode="Markdown")


async def handle_character_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the button click for character selection with a smooth transition."""
    query = update.callback_query
    await query.answer()
    
    char_id = query.data.replace("char_", "")
    user_id = update.effective_user.id
    
    # Update the menu message to show we are switching
    labels = {
        "classmate": "Curious Student",
        "vc": "Skeptical VC",
        "consultant": "Strategic Advisor"
    }
    selected_mode = labels.get(char_id, "that")
    await query.edit_message_text(f"⏳ Switching to {selected_mode} mode...")

    # Send a typing indicator while the AI generates the dynamic intro
    typing_task = start_typing_loop(update.effective_chat.id, context)

    try:
        # Set the character and get the dynamic intro
        first_message = await set_user_character(user_id, char_id)
        
        # Final confirmation
        await query.edit_message_text(f"✅ Teddy is now in {selected_mode} mode.")
        await query.message.reply_text(first_message)
        
        # Start the 24-hour inactivity timer
        schedule_inactivity_ping(update.effective_chat.id, user_id, context)
    finally:
        typing_task.cancel()


async def cmd_sync_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Admin) Sync new NotebookLM projects into Fast Memory.

    Usage:
      /sync_memory          → incremental (only new notebooks)
      /sync_memory force    → re-sync everything visible to the account
    """
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    user_id = str(update.effective_user.id)

    if not admin_id or user_id != admin_id:
        await update.message.reply_text("Oops, only the admin can do that! 🔒")
        return

    force = bool(context.args) and context.args[0].lower() in {"force", "all", "-f"}
    mode = "force re-sync" if force else "incremental sync"
    await update.message.reply_text(f"🧠 Starting {mode}…")
    try:
        import asyncio
        result = await asyncio.to_thread(trigger_memory_sync, force)
        await update.message.reply_text(f"✅ Sync complete!\n\n{result}")
    except Exception as e:
        await update.message.reply_text(f"❌ Sync failed: {e}")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset the conversation history for this user."""
    from agent import _conversations
    user_id = update.effective_user.id
    _conversations.pop(user_id, None)
    await update.message.reply_text(
        "🔄 Conversation reset! Let's start fresh."
    )


def _admin_only(update: Update) -> bool:
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    return bool(admin_id) and str(update.effective_user.id) == admin_id


async def _send_chunks(update: Update, text: str, parse_mode: str | None = None):
    """Telegram caps messages at 4096 chars — split on newlines so we never
    cut through a Markdown entity (an open backtick or `*` at the boundary
    causes Telegram to reject the message with 'can't find end of the entity').
    """
    limit = 3900
    if len(text) <= limit:
        await update.message.reply_text(text, parse_mode=parse_mode)
        return

    buf = ""
    for line in text.splitlines(keepends=True):
        # A single line longer than the limit — hard-split it.
        if len(line) > limit:
            if buf:
                await update.message.reply_text(buf, parse_mode=parse_mode)
                buf = ""
            for i in range(0, len(line), limit):
                await update.message.reply_text(line[i:i + limit], parse_mode=parse_mode)
            continue
        if len(buf) + len(line) > limit:
            await update.message.reply_text(buf, parse_mode=parse_mode)
            buf = ""
        buf += line
    if buf:
        await update.message.reply_text(buf, parse_mode=parse_mode)


async def cmd_list_notebooks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Admin) Show the notebooks the bot's memory is scoped to.

    Usage:
      /list_notebooks        → in-scope only (shared + allowed_own_ids)
      /list_notebooks all    → every notebook visible to the account
    """
    if not _admin_only(update):
        await update.message.reply_text("Oops, admin only 🔒")
        return

    show_all = bool(context.args) and context.args[0].lower() in {"all", "full", "-a"}

    try:
        import asyncio, json
        from notebook_manager import (
            list_all_notebooks,
            filter_in_scope,
            _load_allowed_own_ids,
        )

        all_nbs = await asyncio.to_thread(list_all_notebooks)
        in_scope = filter_in_scope(all_nbs)
        in_scope_ids = {nb["id"] for nb in in_scope}
        allowed_own = _load_allowed_own_ids()
        shared = [nb for nb in in_scope if not nb.get("is_owner", True)]
        own = [nb for nb in in_scope if nb.get("is_owner", True)]

        header = (
            f"Scope: {len(in_scope)} notebook(s) — "
            f"{len(shared)} shared + {len(own)} own (allowlisted).\n"
            f"Visible total on account: {len(all_nbs)}.\n"
        )

        if not show_all:
            lines = [header]
            for i, nb in enumerate(in_scope, 1):
                tag = "🤝 shared" if not nb.get("is_owner", True) else "🔒 own"
                lines.append(
                    f"{i}. {tag} {nb['title']}\n"
                    f"   {nb['id']} · sources: {nb['sources_count']}"
                )
            lines.append(
                "\n(Use /list_notebooks all to also see the "
                f"{len(all_nbs) - len(in_scope)} own notebooks excluded from scope.)"
            )
            await _send_chunks(update, "\n".join(lines))
        else:
            lines = [header]
            for i, nb in enumerate(all_nbs, 1):
                if nb["id"] in in_scope_ids:
                    marker = "✅ in scope"
                elif nb["id"] in allowed_own:
                    marker = "✅ allowlisted"  # defensive — should already be in scope
                else:
                    marker = "⛔ out of scope (own)"
                lines.append(
                    f"{i}. {marker} {nb['title']}\n"
                    f"   {nb['id']} · sources: {nb['sources_count']}"
                )
            await _send_chunks(update, "\n".join(lines))

        await update.message.reply_text(
            "👉 Run /sync_memory to sync the in-scope set into fast memory "
            "and persist the scope for slow memory."
        )
    except Exception as e:
        logger.error("list_notebooks failed", exc_info=True)
        await update.message.reply_text(f"❌ Failed: {type(e).__name__}: {e}")


async def cmd_show_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Admin) Inspect what the bot has synthesised into fast memory.

    Usage:
      /show_memory          → index (titles + sizes)
      /show_memory N        → full distilled content for entry N
    """
    if not _admin_only(update):
        await update.message.reply_text("Oops, admin only 🔒")
        return

    import asyncio
    from memory_manager import get_all_memory

    items = await asyncio.to_thread(get_all_memory)
    if not items:
        await update.message.reply_text(
            "📭 Fast memory is empty. Run /sync_memory first."
        )
        return

    args = context.args or []
    if not args:
        lines = [f"📚 Fast memory: *{len(items)}* document(s).\n"]
        for i, item in enumerate(items, 1):
            m = item["metadata"]
            lines.append(
                f"{i}. *{m.get('title', '?')}* — Week {m.get('week', '?')} "
                f"({len(item['document'])} chars)"
            )
        lines.append(
            "\nUse `/show_memory <N>` to see what was distilled for that entry."
        )
        await _send_chunks(update, "\n".join(lines), parse_mode="Markdown")
        return

    try:
        idx = int(args[0]) - 1
        item = items[idx]
    except (ValueError, IndexError):
        await update.message.reply_text(
            f"Invalid index. Use 1..{len(items)}."
        )
        return

    m = item["metadata"]
    header = (
        f"📄 *{m.get('title', '?')}*\n"
        f"Week {m.get('week', '?')} · by {m.get('student', '?')}\n"
        f"Tags: {m.get('tags', '')}\n"
        f"Notebook ID: `{m.get('notebook_id', '?')}`\n\n"
    )
    await _send_chunks(update, header + item["document"], parse_mode="Markdown")


# ════════════════════════════════════════════════════════════════════════
#  Proactive Engagement (24h Ping)
# ════════════════════════════════════════════════════════════════════════

async def send_inactivity_ping(context: ContextTypes.DEFAULT_TYPE):
    """Fired when a user hasn't spoken in 24 hours."""
    job = context.job
    chat_id = job.chat_id
    user_id = job.data
    
    # Send typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    from agent import generate_proactive_hook
    try:
        message = await generate_proactive_hook(user_id)
        await context.bot.send_message(chat_id=chat_id, text=message)
    except Exception as e:
        logger.error(f"Failed to send proactive hook to {user_id}: {e}")

def schedule_inactivity_ping(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Cancel existing ping jobs and schedule a new one for 24 hours."""
    # Remove existing jobs for this chat
    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in current_jobs:
        job.schedule_removal()
    
    # Schedule a new job 24 hours from now (86400 seconds)
    context.job_queue.run_once(
        send_inactivity_ping, 
        86400, 
        chat_id=chat_id, 
        name=str(chat_id), 
        data=user_id
    )

# ════════════════════════════════════════════════════════════════════════
#  Free-text message handler
# ════════════════════════════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle standard text messages from students."""
    user_id = update.effective_user.id
    user_text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id

    if not user_text:
        return

    typing_task = start_typing_loop(chat_id, context)

    try:
        response = await process_student_message(
            user_id, user_text
        )
        await update.message.reply_text(response)
        
        # Reset the 24-hour inactivity timer since the user just replied
        schedule_inactivity_ping(chat_id, user_id, context)
        
    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        await update.message.reply_text("Brain freeze! 🤯 Try again?")
    finally:
        typing_task.cancel()


# ════════════════════════════════════════════════════════════════════════
#  Bot setup & launch
# ════════════════════════════════════════════════════════════════════════

async def post_init(app):
    """Set bot commands menu after startup."""
    commands = [
        BotCommand("start", "Say hello & get started"),
        BotCommand("character", "Switch your study partner"),
        BotCommand("reset", "Reset conversation history"),
    ]
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    if admin_id:
        commands.append(BotCommand("sync_memory", "Sync case study memory (Admin)"))
        commands.append(BotCommand("list_notebooks", "List NotebookLM projects (Admin)"))
        commands.append(BotCommand("show_memory", "Inspect fast memory (Admin)"))

    await app.bot.set_my_commands(commands)
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


if __name__ == "__main__":
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(bot_token).post_init(post_init).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("character", cmd_character))
    app.add_handler(CommandHandler("sync_memory", cmd_sync_memory))
    app.add_handler(CommandHandler("list_notebooks", cmd_list_notebooks))
    app.add_handler(CommandHandler("show_memory", cmd_show_memory))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CallbackQueryHandler(handle_character_select))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Ecosystem Economy Bot is starting with multi-character support...")
    app.run_polling()
