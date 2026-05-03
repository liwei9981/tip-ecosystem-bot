# Project Handover: TIP Ecosystem "Curious Classmate" Bot

## 📝 Project Overview
The "Curious Classmate" is a Telegram-based AI chatbot designed for the Ecosystem Economy course. It acts as an informal, 20-year-old student who synthesizes shared student case studies, provides opinions, and cross-references them with real-time news.

---

## 🛠 Technical Architecture
- **Brain**: Gemini 3.1 Pro (Large Language Model).
- **Dual-System Thinking**:
  - **Fast Thinking**: Local `chromadb` vector database containing summarized context of all 12 case studies.
  - **Slow Thinking**: Live `notebooklm-py` integration for deep-diving into specific projects.
- **News Engine**: Tavily API for real-time web search.
- **Bot Framework**: `python-telegram-bot` (Async).

---

## ☁️ Deployment & CI/CD
- **Host**: DigitalOcean Droplet (`159.65.133.43`).
- **Runtime**: Docker & Docker Compose.
- **Automation**: GitHub Actions (Auto-deploys on every `git push` to `main`).
- **Persistence**: 
  - `chroma_db/` folder on the server stores the long-term memory.
  - `~/.notebooklm` on the server stores the authenticated browser session.

---

## 🧑‍🎓 Persona: The Curious 20-Year-Old
Defined in `personality.md`:
- **Style**: Concise (max 3 paragraphs), casual, uses contractions, uses humor.
- **Behavior**: Proactively searches news, gives opinions first, always ends with a question.
- **Thinking Messages**: Randomized "thinking" updates to keep the user engaged during long tool calls.

---

## 📚 Knowledge Base (12 Synced Projects)
1.  Session 9 - Samsung (Week 2)
2.  Session 9 - Tata Group
3.  Session 9 - Disney (Adi)
4.  Session 9 - Teletubbies (Alibaba)
5.  Section 9 - Apple (Nadhif)
6.  Section 9 - ByteDance (CAO/SONG)
7.  Session 9 - Ping An (Melvin)
8.  Session 9 - SHEIN (Fast Fashion)
9.  The Ecosystem Economy (Foundational - Week 1)
10. + 3 additional student research notebooks.

---

## 🚀 How to Maintain & Update
### To Update the Persona or Code:
1.  Edit `personality.md` or any `.py` file on your Mac.
2.  Commit and Push:
    ```bash
    git add .
    git commit -m "Update persona"
    git push
    ```
3.  The bot will automatically update on DigitalOcean within ~2 minutes.

### To Sync New Notebooks:
1.  Add the Notebook ID to `config.json`.
2.  Push to GitHub.
3.  Send the `/sync_memory` command to the bot on Telegram (you must be logged in as the admin ID `8688956366`).

### To Check Logs:
Login to DigitalOcean Console and run:
```bash
docker compose -f /app/tip-ecosystem-bot/docker-compose.yml logs -f
```

---

## 🔑 Key Credentials (Stored in .env on Server)
- `TELEGRAM_BOT_TOKEN`: 8358475680:AAEIJURoakhfGj2Qw0_WVDUawTHTkfQXkTA
- `GEMINI_API_KEY`: (See local .env)
- `TAVILY_API_KEY`: (See local .env)
- `ADMIN_TELEGRAM_ID`: 8688956366
