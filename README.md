# 🌱 Ecosystem Economy — Curious Classmate Bot

A Telegram chatbot that acts as a **curious, younger classmate** in a 6-week university course on Ecosystem Economy. It grows smarter each week as students add their case studies to shared NotebookLM projects.

## Architecture

The bot uses a **Dual-System Cognitive Architecture**:

| Mode | Description | Technology |
|------|-------------|------------|
| **Fast Thinking** | Local memory of summarised case studies | ChromaDB vector DB |
| **Slow Thinking** | Deep-dive queries into specific NotebookLM projects | notebooklm-py |
| **News Awareness** | Real-time news search for cross-referencing | Tavily API |

Powered by **Gemini 3.1 Pro** with native tool-calling.

## Setup

1. **Clone & install:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure:**
   ```bash
   cp .env.example .env
   # Fill in: TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, TAVILY_API_KEY, ADMIN_TELEGRAM_ID
   ```

3. **NotebookLM auth** (first time only):
   ```bash
   notebooklm login
   ```

4. **Add case studies** to `config.json` with their NotebookLM IDs.

5. **Run:**
   ```bash
   python bot.py
   ```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Introduce the bot |
| `/reset` | Clear conversation history |
| `/sync_memory` | (Admin) Sync NotebookLM → Fast Memory |

## Weekly Workflow

1. Students create/update their case studies in NotebookLM.
2. Admin adds new notebook IDs to `config.json`.
3. Admin triggers `/sync_memory` to grow the bot's brain.
4. Students chat with the bot — it's now smarter!
