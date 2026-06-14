# TeraBox API & Telegram Bot

This repository contains tools for interacting with TeraBox share links. It has been separated into two independent projects for easier hosting, alongside a standalone script for manual local usage.

## Repository Structure

- `api/`: The Flask API designed to be hosted on Vercel. It provides endpoints for resolving TeraBox file links.
- `dl.py`: A standalone Python script you can run locally to manually download or fetch direct links from a TeraBox share URL using your own cookie.

---

## Telegram Bot (Railway / Docker)

A Telegram bot that acts as a TeraBox downloader, built with Pyrogram and Asyncio. It uses a custom flow API to bypass Terabox limits and handles large files and HLS streams natively using FFMPEG. The source code is in the root directory.

### Running with Docker

You can easily run the bot using the provided Dockerfile. This ensures all dependencies, including FFMPEG, are correctly installed.

1.  Build the Docker image:
    ```bash
    docker build -t terabox-bot .
    ```

2.  Run the Docker container, providing your environment variables:
    ```bash
    docker run -d --name terabox-bot \
        -e BOT_TOKEN="your_bot_token" \
        -e BOT_API_ID="your_api_id" \
        -e BOT_API_HASH="your_api_hash" \
        -e MONGO_URI="your_mongodb_uri" \
        -e OWNER_ID="your_telegram_id" \
        terabox-bot
    ```

### Running Locally without Docker

**Requirements:**
- Python 3.9+
- FFMPEG installed on your system (required for processing streaming video links).

**Deployment:**
1. Install dependencies: `pip install -r requirements.txt`
2. Install FFMPEG:
   - Ubuntu/Debian: `sudo apt-get update && sudo apt-get install -y ffmpeg`
   - MacOS: `brew install ffmpeg`
3. Set your environment variables (`BOT_TOKEN`, `BOT_API_ID`, `BOT_API_HASH`, `MONGO_URI`) in a `.env` file or directly in your hosting provider's dashboard.
4. Run the bot:
    ```bash
    python main.py
    ```
