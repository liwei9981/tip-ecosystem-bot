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
    set_user_character
)

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

load_dotenv()


# ════════════════════════════════════════════════════════════════════════
#  Command handlers
# ════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start — introduce the classmate and characters."""
    user = update.effective_user
    name = user.first_name if user else "there"
    
    welcome_text = (
        f"Hey {name}! 👋\n\n"
        "Welcome to our Ecosystem Economy study group! I've prepared three different "
        "perspectives to help you deconstruct the case studies.\n\n"
        "Please pick your study partner below to get started:"
    )
    
    await show_character_menu(update)


async def cmd_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to switch characters manually."""
    await show_character_menu(update)


async def show_character_menu(update: Update):
    """Helper to show a simple, concise character selection keyboard."""
    chars = get_available_characters()
    
    # Simple, non-descriptive labels
    labels = {
        "classmate": "Leo 🧑‍🎓",
        "vc": "Alex 🦈",
        "consultant": "Beatrice 📊"
    }
    
    keyboard = []
    for char_id, char_name in chars.items():
        btn_text = labels.get(char_id, char_name)
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"char_{char_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "Select your study partner:"
    
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
    chars = get_available_characters()
    selected_name = chars.get(char_id, char_id)
    await query.edit_message_text(f"⏳ Calling {selected_name} into the session...")

    # Send a typing indicator while the AI generates the dynamic intro
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    # Set the character and get the dynamic intro
    first_message = await set_user_character(user_id, char_id)
    
    # Final confirmation and the character's "Hi"
    await query.edit_message_text(f"✅ {selected_name} has joined the chat.")
    await query.message.reply_text(first_message)


async def cmd_sync_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (same as before)
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    user_id = str(update.effective_user.id)

    if not admin_id or user_id != admin_id:
        await update.message.reply_text("Oops, only the admin can do that! 🔒")
        return

    await update.message.reply_text("🧠 Starting memory sync...")
    try:
        result = trigger_memory_sync()
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

    # Send typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    import random
    async def notify_thinking(tool_name: str):
        # ... (same variety as before)
        messages = {
            "query_notebook_project": ["Reading the case study... 📚", "Digging into notes... 🧐"],
            "search_latest_news": ["Checking the news... 📰", "Scanning headlines... 🚀"],
            "search_case_study_memory": ["Connecting the dots... 🧠", "Thinking... 💡"]
        }
        pool = messages.get(tool_name, ["Thinking... 🚀"])
        await update.message.reply_text(random.choice(pool))

    try:
        response = await process_student_message(
            user_id, user_text, on_slow_tool_start=notify_thinking
        )
        await update.message.reply_text(response)
    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        await update.message.reply_text("Brain freeze! 🤯 Try again?")


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

    await app.bot.set_my_commands(commands)
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


if __name__ == "__main__":
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(bot_token).post_init(post_init).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("character", cmd_character))
    app.add_handler(CommandHandler("sync_memory", cmd_sync_memory))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CallbackQueryHandler(handle_character_select))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Ecosystem Economy Bot is starting with multi-character support...")
    app.run_polling()
