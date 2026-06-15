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
