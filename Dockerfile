# Use Python 3.10 slim as base
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies for Playwright and ChromaDB
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers and dependencies
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy the rest of the application
COPY . .

# Create directory for ChromaDB and NotebookLM persistence
RUN mkdir -p /app/data && mkdir -p /root/.notebooklm

# Run the bot
CMD ["python", "bot.py"]
