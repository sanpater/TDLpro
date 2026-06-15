# TeraBox Telegram Bot

This repository contains a high-speed Telegram bot for downloading files from TeraBox share links. The codebase is organized into a modular structure for easy maintenance and readability.

## Repository Structure

- `main.py`: The entry point for running the bot.
- `config.py`: Environment variable loading and configuration.
- `core/`: Core functionality, including database interactions (`database.py`) and API logic (`flowapi.py`).
- `handlers/`: Telegram message and callback handlers (e.g., `commands.py`, `links.py`, `callbacks.py`).
- `utils/`: Helper scripts, downloading logic, and progress bar generation.

---

## 1. Deployment (Docker)

You can deploy the bot easily using the provided `Dockerfile`.

**Prerequisites:**
1. A Telegram Bot Token from [BotFather](https://t.me/BotFather).
2. Telegram API ID and API HASH from [my.telegram.org](https://my.telegram.org/).
3. Create a `.env` file containing your credentials (or pass them to the docker container).

**Example `.env` file:**
```env
BOT_TOKEN=your_bot_token_here
BOT_API_ID=your_api_id
BOT_API_HASH=your_api_hash
OWNER_ID=your_user_id
# Optional
DUMP_CHANNEL_ID=-100xxxxxxx
```

**Build and Run:**
```bash
docker build -t terabox_bot .
docker run -d --env-file .env terabox_bot
```

---

## 2. Local Usage

To run the bot locally without Docker:

```bash
# Optional: create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Run the bot
python main.py
```

*Note: Ensure `ffmpeg` is installed on your local machine if you want accurate video duration extraction.*
