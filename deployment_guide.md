# Deployment Guide: Ecosystem Economy Bot

This guide explains how to deploy your "Curious Classmate" bot to a cloud server (VPS) like DigitalOcean, AWS, or GCP.

## Prerequisites
1. A server running Linux (Ubuntu recommended).
2. Docker and Docker Compose installed on the server.
3. Your local `.env` file with all API keys.
4. Your authenticated NotebookLM session (stored in `~/.notebooklm`).

## Step 1: Transfer Files to Server
Copy the following files/folders to your server (e.g., into `/home/ubuntu/tip-bot/`):
- `Dockerfile`
- `docker-compose.yml`
- `requirements.txt`
- `bot.py`, `agent.py`, `memory_manager.py`, `notebook_manager.py`, `news_fetcher.py`
- `config.json`
- `personality.md`
- `.env`

## Step 2: Transfer NotebookLM Session
The bot uses browser-based auth. You MUST copy your local authentication tokens to the server so the bot can log in without a headful browser.

On your local Mac, run:
```bash
scp -r ~/.notebooklm user@your-server-ip:~/.notebooklm
```

## Step 3: Launch the Bot
On your server, navigate to the project directory and run:
```bash
docker-compose up -d --build
```

## Step 4: Verify
Check the logs to make sure everything is running smoothly:
```bash
docker-compose logs -f
```

---

## Alternative: Railway / Render (PaaS)
If you prefer a simpler "Push to GitHub" deployment:
1. Push your code to a private GitHub repository.
2. Connect the repo to **Railway.app**.
3. Add all your `.env` variables in the Railway dashboard.
4. **Note**: Persistence and NotebookLM auth are trickier on PaaS. The VPS + Docker method is recommended for this specific bot because of the browser-based auth requirements.
