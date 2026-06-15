import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from core.database import db
from config import OWNER_ID

@Client.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    await db.add_user(user_id)
    await message.reply_text(
        "🎉 Welcome! I am a high-speed TeraBox downloader bot.\n\n"
        "🔗 Send me a TeraBox link and I'll securely download and send you the file directly here.\n"
        "🛑 Use /cancel to stop all your active downloads.\n"
        "🌐 Supported domains: terabox.com, teraboxapp.com, etc."
    )

@Client.on_message(filters.command("block") & filters.user(OWNER_ID) if OWNER_ID else filters.command("block") & filters.user([]))
async def block_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /block <user_id>")
    try:
        user_id = int(message.command[1])
        await db.block_user(user_id)
        await message.reply_text(f"User {user_id} blocked successfully.")
    except ValueError:
        await message.reply_text("Invalid user ID.")

@Client.on_message(filters.command("unblock") & filters.user(OWNER_ID) if OWNER_ID else filters.command("unblock") & filters.user([]))
async def unblock_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /unblock <user_id>")
    try:
        user_id = int(message.command[1])
        await db.unblock_user(user_id)
        await message.reply_text(f"User {user_id} unblocked successfully.")
    except ValueError:
        await message.reply_text("Invalid user ID.")

@Client.on_message(filters.command("approve") & filters.user(OWNER_ID) if OWNER_ID else filters.command("approve") & filters.user([]))
async def approve_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /approve <user_id>")
    try:
        user_id = int(message.command[1])
        await db.approve_user(user_id)
        await message.reply_text(f"User {user_id} approved successfully. They now have no limits.")
    except ValueError:
        await message.reply_text("Invalid user ID.")

@Client.on_message(filters.command("disapprove") & filters.user(OWNER_ID) if OWNER_ID else filters.command("disapprove") & filters.user([]))
async def disapprove_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /disapprove <user_id>")
    try:
        user_id = int(message.command[1])
        await db.disapprove_user(user_id)
        await message.reply_text(f"User {user_id} disapproved successfully. They are back to normal limits.")
    except ValueError:
        await message.reply_text("Invalid user ID.")

@Client.on_message(filters.command("broadcast") & filters.user(OWNER_ID) if OWNER_ID else filters.command("broadcast") & filters.user([]))
async def broadcast_command(client: Client, message: Message):
    if not message.reply_to_message and len(message.command) < 2:
        return await message.reply_text("Usage: /broadcast <message> or reply to a message.")

    users = await db.get_all_users()
    total_users = len(users)
    await message.reply_text(f"Broadcasting to {total_users} users...")

    sent = 0
    failed = 0
    for user in users:
        try:
            if message.reply_to_message:
                await message.reply_to_message.copy(user["user_id"])
            else:
                msg_text = message.text.split(maxsplit=1)[1]
                await client.send_message(user["user_id"], msg_text)
            sent += 1
            await asyncio.sleep(0.1) # Prevent FloodWait
        except Exception:
            failed += 1

    await message.reply_text(f"Broadcast completed.\nSent: {sent}\nFailed: {failed}")

@Client.on_message(filters.command("setmax") & filters.user(OWNER_ID) if OWNER_ID else filters.command("setmax") & filters.user([]))
async def setmax_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /setmax <size_in_MB>")
    try:
        max_mb = float(message.command[1])
        await db.update_settings("max_file_size_bytes", max_mb * 1024 * 1024)
        await message.reply_text(f"Max file size set to {max_mb:.2f} MB.")
    except ValueError:
        await message.reply_text("Invalid size value.")

@Client.on_message(filters.command("setmin") & filters.user(OWNER_ID) if OWNER_ID else filters.command("setmin") & filters.user([]))
async def setmin_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /setmin <size_in_MB>")
    try:
        min_mb = float(message.command[1])
        await db.update_settings("min_file_size_bytes", min_mb * 1024 * 1024)
        await message.reply_text(f"Min file size set to {min_mb:.2f} MB.")
    except ValueError:
        await message.reply_text("Invalid size value.")

@Client.on_message(filters.command("setlimit") & filters.user(OWNER_ID) if OWNER_ID else filters.command("setlimit") & filters.user([]))
async def setlimit_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /setlimit <number_of_links>")
    try:
        limit = int(message.command[1])
        await db.update_settings("daily_limit", limit)
        await message.reply_text(f"Daily download limit set to {limit} links.")
    except ValueError:
        await message.reply_text("Invalid limit value.")

@Client.on_message(filters.command("settings") & filters.user(OWNER_ID) if OWNER_ID else filters.command("settings") & filters.user([]))
async def settings_command(client: Client, message: Message):
    settings = await db.get_settings()
    max_mb = settings.get("max_file_size_bytes", db.default_settings["max_file_size_bytes"]) / (1024 * 1024)
    min_mb = settings.get("min_file_size_bytes", db.default_settings["min_file_size_bytes"]) / (1024 * 1024)
    limit = settings.get("daily_limit", db.default_settings["daily_limit"])

    text = (
        "⚙️ **Current Global Settings:**\n\n"
        f"**Daily Limit:** `{limit}` links\n"
        f"**Max File Size:** `{max_mb:.2f}` MB\n"
        f"**Min File Size:** `{min_mb:.2f}` MB"
    )
    await message.reply_text(text)

@Client.on_message(filters.command("log") & filters.user(OWNER_ID) if OWNER_ID else filters.command("log") & filters.user([]))
async def log_command(client: Client, message: Message):
    if os.path.exists("bot.log"):
        await message.reply_document("bot.log")
    else:
        await message.reply_text("Log file not found.")

@Client.on_message(filters.command("cancel"))
async def cancel_command(client: Client, message: Message):
    from config import user_tasks
    from pyrogram.enums import ParseMode
    user_id = message.from_user.id
    if user_id in user_tasks and user_tasks[user_id]:
        for task in user_tasks[user_id]:
            task.cancel()
        user_tasks[user_id] = []
        await message.reply_text("🛑 <b>All your tasks have been cancelled.</b>", parse_mode=ParseMode.HTML)
    else:
        await message.reply_text("You have no running tasks.")
