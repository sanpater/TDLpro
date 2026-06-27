import pyrogram.utils
from pyrogram import Client
import asyncio
from config import API_ID, API_HASH, BOT_TOKEN, DUMP_CHANNEL_ID, logger
from web import run_web_server

# Monkey-patch Pyrogram's hardcoded limits to avoid "Peer id invalid" errors for newer channels
pyrogram.utils.MIN_CHANNEL_ID = -100999999999999
pyrogram.utils.MIN_CHAT_ID = -9999999999999

# Initialize bot client
# in_memory=False prevents SQLite DB creation/writes for peer caches which saves some background RAM/IO
app = Client(
    "terabox_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="handlers"),
    in_memory=False
)

async def main():
    await app.start()
    logger.info("Bot started.")

    if DUMP_CHANNEL_ID:
        try:
            await app.get_chat(DUMP_CHANNEL_ID)
            logger.info(f"Successfully fetched DUMP_CHANNEL_ID ({DUMP_CHANNEL_ID}) chat info.")
        except Exception as e:
            logger.warning(f"Could not fetch DUMP_CHANNEL_ID ({DUMP_CHANNEL_ID}) directly: {e}. Attempting to resolve via raw API...")
            try:
                from pyrogram.raw.functions.channels import GetChannels
                from pyrogram.raw.types import InputChannel

                channel_id = pyrogram.utils.get_channel_id(DUMP_CHANNEL_ID)
                # For bots that are admins of the channel, access_hash=0 is allowed to fetch channel info
                await app.invoke(GetChannels(id=[InputChannel(channel_id=channel_id, access_hash=0)]))

                # Fetch again now that Pyrogram has cached the peer from the raw response
                await app.get_chat(DUMP_CHANNEL_ID)
                logger.info("Successfully fetched and cached DUMP_CHANNEL_ID using raw API.")
            except Exception as e2:
                logger.error(f"Failed to resolve DUMP_CHANNEL_ID via raw API. Ensure the bot is an admin in the channel. Error: {e2}")

    from pyrogram import idle
    await idle()
    await app.stop()
    logger.info("Bot stopped.")

if __name__ == "__main__":
    import traceback

    logger.info("Starting web server on port 7860...")
    try:
        run_web_server()
    except Exception as e:
        logger.error(f"Failed to start web server: {e}")
        logger.error(traceback.format_exc())

    logger.info("Starting bot...")
    try:
        app.run(main())
    except Exception as e:
        logger.error(f"Bot stopped due to an exception: {e}")
        logger.error(traceback.format_exc())
