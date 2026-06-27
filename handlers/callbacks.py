from pyrogram import Client, filters
from pyrogram.types import CallbackQuery
from pyrogram.enums import ParseMode
from config import user_tasks

@Client.on_callback_query(filters.regex("^cancel_tasks$"))
async def cancel_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id in user_tasks and user_tasks[user_id]:
        for task in user_tasks[user_id]:
            task.cancel()
        user_tasks[user_id] = []
        await callback_query.message.edit_text("🛑 <b>Task Cancelled.</b>", parse_mode=ParseMode.HTML)
    else:
        await callback_query.answer("No running tasks to cancel.", show_alert=True)

from core.database import db

@Client.on_callback_query(filters.regex("^(set_limit_up|set_limit_down|set_force_channel|close_settings)$"))
async def settings_callback(client: Client, callback_query: CallbackQuery):
    from config import OWNER_ID
    if callback_query.from_user.id != OWNER_ID:
        return await callback_query.answer("Only the owner can do this.", show_alert=True)
        
    data = callback_query.data
    settings = await db.get_settings()
    
    if data == "close_settings":
        await callback_query.message.delete()
        return
        
    if data == "set_limit_up":
        limit = settings.get("daily_limit", db.default_settings["daily_limit"]) + 5
        await db.update_settings("daily_limit", limit)
    elif data == "set_limit_down":
        limit = max(0, settings.get("daily_limit", db.default_settings["daily_limit"]) - 5)
        await db.update_settings("daily_limit", limit)
    elif data == "set_force_channel":
        await callback_query.answer("Please use /setforcechannel <channel_id> to set the force channel.", show_alert=True)
        return
        
    # Update message
    settings = await db.get_settings()
    max_mb = settings.get("max_file_size_bytes", db.default_settings["max_file_size_bytes"]) / (1024 * 1024)
    min_mb = settings.get("min_file_size_bytes", db.default_settings["min_file_size_bytes"]) / (1024 * 1024)
    limit = settings.get("daily_limit", db.default_settings["daily_limit"])
    force_channel = settings.get("force_channel_id", "")

    text = (
        "⚙️ **Current Global Settings:**\n\n"
        f"**Daily Limit:** `{limit}` links\n"
        f"**Max File Size:** `{max_mb:.2f}` MB\n"
        f"**Min File Size:** `{min_mb:.2f}` MB\n"
        f"**Force Channel ID:** `{force_channel if force_channel else 'None'}`"
    )
    
    markup = callback_query.message.reply_markup
    await callback_query.message.edit_text(text, reply_markup=markup)

