import os
from dotenv import load_dotenv

load_dotenv()

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
