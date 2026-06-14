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
            logger.warning(f"Could not fetch DUMP_CHANNEL_ID ({DUMP_CHANNEL_ID}) directly: {e}. Attempting to resolve via raw API...")
            try:
                from pyrogram.raw.functions.channels import GetChannels
                from pyrogram.raw.types import InputChannel
                import pyrogram.utils

                channel_id = pyrogram.utils.get_channel_id(DUMP_CHANNEL_ID)
                await app.invoke(GetChannels(id=[InputChannel(channel_id=channel_id, access_hash=0)]))

                await app.get_chat(DUMP_CHANNEL_ID)
                logger.info("Successfully fetched and cached DUMP_CHANNEL_ID using raw API.")
            except Exception as e2:
                logger.error(f"Failed to resolve DUMP_CHANNEL_ID via raw API. Ensure the bot is an admin in the channel. Error: {e2}")

    await pyrogram.idle()
    await app.stop()
    logger.info("Bot stopped.")

if __name__ == "__main__":
    logger.info("Starting bot...")
    app.run(main())
