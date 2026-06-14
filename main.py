import asyncio
import logging
import pyrogram

from core.bot import app
from core.config import DUMP_CHANNEL_ID
from handlers.commands import register_commands
from handlers.messages import register_message_handlers

logger = logging.getLogger(__name__)

async def main():
    register_commands(app)
    register_message_handlers(app)

    await app.start()
    logger.info("Bot started.")

    if DUMP_CHANNEL_ID:
        try:
            await app.get_chat(DUMP_CHANNEL_ID)
            logger.info(f"Successfully fetched DUMP_CHANNEL_ID ({DUMP_CHANNEL_ID}) chat info.")
        except Exception as e:
            # Silently fallback to raw API to cache the chat if standard get_chat fails
            try:
                from pyrogram.raw.functions.channels import GetChannels
                from pyrogram.raw.types import InputChannel
                import pyrogram.utils

                channel_id = pyrogram.utils.get_channel_id(DUMP_CHANNEL_ID)
                await app.invoke(GetChannels(id=[InputChannel(channel_id=channel_id, access_hash=0)]))

                await app.get_chat(DUMP_CHANNEL_ID)
                logger.info("Successfully fetched and cached DUMP_CHANNEL_ID using raw API.")
            except Exception as e2:
                if "CHANNEL_INVALID" in str(e2):
                    logger.error(f"Failed to resolve DUMP_CHANNEL_ID ({DUMP_CHANNEL_ID}). Since you are running in Docker without a persistent .session volume, please forward a message from the Dump Channel to the bot so it can cache the channel's access hash, or ensure the bot is an admin in the channel. Raw error: {e2}")
                else:
                    logger.error(f"Failed to resolve DUMP_CHANNEL_ID ({DUMP_CHANNEL_ID}) via raw API after standard method failed. Error: {e}. Raw fallback error: {e2}")

    await pyrogram.idle()
    await app.stop()
    logger.info("Bot stopped.")

if __name__ == "__main__":
    logger.info("Starting bot...")
    app.run(main())
