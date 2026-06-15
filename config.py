import os
import asyncio
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("terabox_bot")

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("BOT_API_ID")
API_HASH = os.getenv("BOT_API_HASH")
DUMP_CHANNEL_ID = os.getenv("DUMP_CHANNEL_ID")
OWNER_ID = os.getenv("OWNER_ID")
API_URL = os.getenv("API_URL", "https://td-l.vercel.app/api2")

if OWNER_ID:
    try:
        OWNER_ID = int(OWNER_ID)
    except ValueError:
        pass

if DUMP_CHANNEL_ID:
    try:
        DUMP_CHANNEL_ID = int(DUMP_CHANNEL_ID)
    except ValueError:
        pass

if not BOT_TOKEN or not API_ID or not API_HASH:
    logger.warning("Bot credentials are not fully set. Please check your .env file.")

# Concurrency control for downloads/uploads (max concurrent operations)
MAX_CONCURRENT_TASKS = 80
semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

# Track running tasks by user_id for cancellation
user_tasks = {}
