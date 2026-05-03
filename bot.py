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
from telegram import Update, BotCommand, MenuButtonCommands
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from agent import process_student_message, trigger_memory_sync

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
    """Handle /start — introduce the curious classmate."""
    user = update.effective_user
    name = user.first_name if user else "there"
    logger.info(
        "[chat %s] /start from %s (id=%s)",
        update.effective_chat.id,
        user.full_name if user else "unknown",
        user.id if user else "?",
    )

    welcome_text = (
        f"Hey {name}! 👋\n\n"
        "I'm your classmate in our Ecosystem Economy course! "
        "I've been reading through everyone's case studies and I'm "
        "really curious about what you've been working on.\n\n"
        "I can:\n"
        "💭 Discuss ideas from any of our shared case studies\n"
        "📰 Look up the latest news related to what we're studying\n"
        "🔍 Deep-dive into specific projects for more details\n\n"
        "The more case studies we add, the smarter I get! "
        "So, what's on your mind today?"
    )
    await update.message.reply_text(welcome_text)


async def cmd_sync_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to manually trigger Fast Memory synchronization."""
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    user_id = str(update.effective_user.id)

    if not admin_id or user_id != admin_id:
        await update.message.reply_text(
            "Oops, only the admin can do that! 🔒"
        )
        return

    await update.message.reply_text(
        "🧠 Starting memory sync from NotebookLM projects...\n"
        "This might take a few minutes — I need to read through "
        "all the case studies!"
    )
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )

    try:
        result = trigger_memory_sync()
        await update.message.reply_text(
            f"✅ Sync complete! I'm feeling smarter already 🧠\n\n{result}"
        )
    except Exception as e:
        logger.error("Sync failed: %s", e, exc_info=True)
        await update.message.reply_text(
            f"❌ Sync hit a snag: {e}\n\nPlease check the logs."
        )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset the conversation history for this user."""
    from agent import _conversations
    user_id = update.effective_user.id
    _conversations.pop(user_id, None)
    await update.message.reply_text(
        "🔄 Conversation reset! Let's start fresh. What shall we talk about?"
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

    logger.info(
        "[chat %s] Message from %s: %s",
        chat_id, user_id, user_text[:80],
    )

    # Send typing indicator while the agent thinks
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    import random

    async def notify_thinking(tool_name: str):
        """Callback for tool triggers with variety and humor."""
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        
        messages = {
            "query_notebook_project": [
                "Hang on, let me quickly re-read that case study... I want to make sure I get the details right! 📚",
                "Ooh, let me dig into our class notes for that one. Back in a sec! 🧐",
                "Give me a moment to dive into the archives... the student who wrote this case study went deep! 🤿",
                "Wait, I remember something about this in the shared notebooks. Let me find the exact page... 🕵️‍♂️",
            ],
            "search_latest_news": [
                "Let me check the latest news on this. Things move fast in the ecosystem world! 📰",
                "Wait, I think I saw something about this recently. Let me quickly google the latest... 🌐",
                "Hold up, let me see what's actually happening out there right now! 🚀",
                "Let me scan the headlines real quick to see if there's any fresh tea on this. ☕️",
            ],
            "search_case_study_memory": [
                "Thinking... I've got this somewhere in my brain... 🧠",
                "Give me a sec to connect the dots... 💡",
                "Hmm, let me process that... 🧩",
            ]
        }
        
        # Pick a message based on the tool or a default one
        pool = messages.get(tool_name, ["Thinking... hang tight! 🚀"])
        await update.message.reply_text(random.choice(pool))

    try:
        response = await process_student_message(
            user_id, user_text, on_slow_tool_start=notify_thinking
        )
        await update.message.reply_text(response)

    except Exception as e:
        logger.error(
            "[chat %s] Error processing message: %s", chat_id, e, exc_info=True
        )
        await update.message.reply_text(
            "My brain is a bit scrambled right now 🤯 "
            "Could you try asking that again?"
        )



# ════════════════════════════════════════════════════════════════════════
#  Bot setup & launch
# ════════════════════════════════════════════════════════════════════════

async def post_init(app):
    """Set bot commands menu after startup."""
    commands = [
        BotCommand("start", "Say hello & get started"),
        BotCommand("reset", "Reset conversation history"),
    ]
    # Add admin command if admin ID is set
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    if admin_id:
        commands.append(BotCommand("sync_memory", "Sync case study memory (Admin)"))

    await app.bot.set_my_commands(commands)
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


if __name__ == "__main__":
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token or bot_token == "your_telegram_bot_token_here":
        print(
            "❌ Please set TELEGRAM_BOT_TOKEN in your .env file.\n"
            "   Copy .env.example → .env and fill in the values."
        )
        exit(1)

    app = ApplicationBuilder().token(bot_token).post_init(post_init).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("sync_memory", cmd_sync_memory))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("🤖 Curious Classmate Bot is starting...")
    app.run_polling()
