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
    import asyncio
    async def keep_typing():
        try:
            while True:
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    typing_task = asyncio.create_task(keep_typing())
    
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

    import asyncio
    async def keep_typing():
        try:
            while True:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    typing_task = asyncio.create_task(keep_typing())

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
