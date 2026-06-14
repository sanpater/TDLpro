import logging
import pyrogram.utils
from pyrogram import Client
from core.config import API_ID, API_HASH, BOT_TOKEN

pyrogram.utils.MIN_CHANNEL_ID = -100999999999999
pyrogram.utils.MIN_CHAT_ID = -9999999999999

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN or not API_ID or not API_HASH:
    logger.warning("Bot credentials are not fully set. Please check your .env file.")

app = Client(
    "terabox_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)
