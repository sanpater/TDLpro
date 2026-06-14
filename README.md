# TeraBox API & Telegram Bot

This repository contains tools for interacting with TeraBox share links. It has been separated into two independent projects for easier hosting, alongside a standalone script for manual local usage.

## Repository Structure

- `api/`: The Flask API designed to be hosted on Vercel. It provides endpoints for resolving TeraBox file links.
- `bot/`: The Telegram bot designed to be hosted on Railway. It uses pyrogram to automatically download and send files from TeraBox links sent in chat.
- `dl.py`: A standalone Python script you can run locally to manually download or fetch direct links from a TeraBox share URL using your own cookie.

---

## 1. API (Vercel)

The API extracts file information from TeraBox share links.

**Deployment:**
1. Navigate to the `api/` directory.
2. Deploy directly to Vercel using the provided `vercel.json`.
3. Make sure to set up your environment variables (like `COOKIE_JSON`) in the Vercel dashboard.

**Local Usage:**
```bash
cd api
pip install -r requirements.txt
python main.py
```

---

## 2. Telegram Bot (Railway)

A Telegram bot that acts as a TeraBox downloader.

**Deployment:**
1. Navigate to the `bot/` directory.
2. Deploy to Railway or a similar service.
3. Set your environment variables (`BOT_TOKEN`, `BOT_API_ID`, `BOT_API_HASH`, `API_URL`) in your hosting provider's dashboard.
   - `API_URL`: The URL of your deployed Vercel API (e.g., `https://td-l.vercel.app/api2`). If you don't set this, it will default to a placeholder.
   - Note: The bot no longer requires a `COOKIE_JSON`.

**Local Usage:**
```bash
cd bot
pip install -r requirements.txt
python bot.py
```

---

## 3. Standalone Script (`dl.py`)

A single-file script that allows you to manually fetch direct download links for any TeraBox URL. It requires no external dependencies other than `aiohttp`.

**Usage:**
```bash
python3 dl.py "https://1024terabox.com/s/1_8lO2hqOmptouVBSn8tJcg" -c "YOUR_NDUS_COOKIE_HERE"
```

**Options:**
- `-c, --cookie`: **Required.** Your TeraBox `ndus` cookie value.
- `-p, --password`: Optional. The password if the link is protected.