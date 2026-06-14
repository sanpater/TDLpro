import os
import asyncio
import logging
import aiohttp
import aiofiles
import pyrogram

from pyrogram import Client, filters
from pyrogram.enums import ParseMode, ChatType, ChatAction
from pyrogram.errors import FloodWait
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from dotenv import load_dotenv

import time

from flowapi import get_flowvideo_links
from hachoir.parser import createParser
from hachoir.metadata import extractMetadata

from database import db

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
logger = logging.getLogger(__name__)

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

# Concurrency control for downloads/uploads (max concurrent operations)
MAX_CONCURRENT_TASKS = 80
semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

# Track running tasks by user_id for cancellation
user_tasks = {}

if not BOT_TOKEN or not API_ID or not API_HASH:
    logger.warning("Bot credentials are not fully set. Please check your .env file.")

def format_bytes(size):
    size = int(size)
    power = 2**10
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}B"

import subprocess

def get_video_duration(filepath):
    try:
        # First try using ffprobe (requires ffmpeg installed on host)
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of",
             "default=noprint_wrappers=1:nokey=1", filepath],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        duration = float(result.stdout)
        return int(duration)
    except Exception as ffmpeg_err:
        logger.warning(f"ffprobe failed for {filepath}: {ffmpeg_err}, falling back to hachoir")
        # Fallback to hachoir
        try:
            parser = createParser(filepath)
            if not parser:
                return 0
            metadata = extractMetadata(parser)
            if metadata and metadata.has("duration"):
                return metadata.get("duration").seconds
        except Exception as e:
            logger.warning(f"Failed to extract video duration for {filepath} with hachoir: {e}")
    return 0

def format_time(seconds):
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

async def fast_download(url, headers, filepath, status_msg, action_text, start_time, last_update_time, max_concurrent=20):
    """Downloads a file fast by using multiple concurrent connections if the server supports range requests."""
    # Create an explicit TCP connector with a low limit to prevent pooling overhead
    connector = aiohttp.TCPConnector(limit=max_concurrent)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Check if the server supports range requests
        async with session.head(url, headers=headers, allow_redirects=True) as resp:
            total_size = int(resp.headers.get("content-length", 0))
            accept_ranges = resp.headers.get("accept-ranges", "none")

        if total_size > 0 and accept_ranges == "bytes":
            # Concurrent download
            chunk_size = total_size // max_concurrent
            ranges = []
            for i in range(max_concurrent):
                start = i * chunk_size
                end = total_size - 1 if i == max_concurrent - 1 else (i + 1) * chunk_size - 1
                ranges.append((start, end))

            downloaded = [0] * max_concurrent

            async def download_chunk(i, start, end):
                current_start = start
                retries = 5
                part_file = f"{filepath}.part{i}"

                # Create or truncate the file initially
                async with aiofiles.open(part_file, "wb") as f:
                    pass

                while current_start <= end and retries > 0:
                    try:
                        chunk_headers = headers.copy()
                        chunk_headers["Range"] = f"bytes={current_start}-{end}"
                        async with session.get(url, headers=chunk_headers) as chunk_resp:
                            if chunk_resp.status not in (200, 206):
                                logger.error(f"Failed chunk {i} with status {chunk_resp.status}")
                                break

                            async with aiofiles.open(part_file, "ab") as f:
                                buffer = bytearray()
                                while True:
                                    chunk = await chunk_resp.content.read(1024 * 1024)
                                    if not chunk:
                                        if buffer:
                                            await f.write(buffer)
                                        break
                                    buffer.extend(chunk)
                                    downloaded[i] += len(chunk)
                                    current_start += len(chunk)

                                    # Buffer up to 2MB to prevent RAM exhaustion and too many disk writes
                                    if len(buffer) >= 2 * 1024 * 1024:
                                        await f.write(buffer)
                                        buffer.clear()

                                    total_downloaded = sum(downloaded)
                                    await progress_bar(total_downloaded, total_size, status_msg, action_text, start_time, last_update_time)

                        # If we break cleanly and current_start is strictly greater than end, chunk is fully downloaded
                        if current_start > end:
                            break

                    except (aiohttp.ClientPayloadError, aiohttp.ClientError, asyncio.TimeoutError) as e:
                        retries -= 1
                        logger.warning(f"Chunk {i} interrupted ({e}). Retrying from {current_start}... ({retries} retries left)")
                        await asyncio.sleep(2)
                        if retries <= 0:
                            logger.error(f"Chunk {i} failed after all retries.")
                            raise e
                    except Exception as e:
                        logger.error(f"Unexpected error in chunk {i}: {e}")
                        raise e

            tasks = [download_chunk(i, start, end) for i, (start, end) in enumerate(ranges)]
            await asyncio.gather(*tasks)

            # Combine parts
            async with aiofiles.open(filepath, "wb") as outfile:
                for i in range(max_concurrent):
                    part_file = f"{filepath}.part{i}"
                    async with aiofiles.open(part_file, "rb") as infile:
                        while True:
                            chunk = await infile.read(10 * 1024 * 1024)
                            if not chunk:
                                break
                            await outfile.write(chunk)
                    os.remove(part_file)
            return True
        else:
            # Fallback to single-connection chunked download
            async with session.get(url, headers=headers, allow_redirects=True) as resp:
                if resp.status != 200:
                    return False
                total_size = int(resp.headers.get("content-length", 0))
                downloaded = 0
                async with aiofiles.open(filepath, "wb") as f:
                    buffer = bytearray()
                    while True:
                        chunk = await resp.content.read(1024 * 1024)
                        if not chunk:
                            if buffer:
                                await f.write(buffer)
                            break
                        buffer.extend(chunk)
                        downloaded += len(chunk)

                        if len(buffer) >= 2 * 1024 * 1024:
                            await f.write(buffer)
                            buffer.clear()

                        if total_size > 0:
                            await progress_bar(downloaded, total_size, status_msg, action_text, start_time, last_update_time)
                return True

async def progress_bar(current, total, status_msg, action_text, start_time, last_update_time):
    now = time.time()
    # Update every 2 seconds
    if now - last_update_time[0] < 3.0 and current != total:
        return

    last_update_time[0] = now

    if total == 0:
        total = 1 # Prevent division by zero

    percentage = current * 100 / total
    speed = current / (now - start_time) if now - start_time > 0 else 0
    eta = (total - current) / speed if speed > 0 else 0

    progress_str = "[{0}{1}] {2}%\n".format(
        ''.join(["●" for i in range(int(percentage / 10))]),
        ''.join(["○" for i in range(10 - int(percentage / 10))]),
        round(percentage, 2)
    )

    text = f"🔄 <b>{action_text}</b>\n\n"
    text += f"{progress_str}"
    text += f"📦 <b>Size:</b> {format_bytes(current)} / {format_bytes(total)}\n"
    text += f"🚀 <b>Speed:</b> {format_bytes(speed)}/s\n"
    text += f"⏳ <b>ETA:</b> {format_time(eta)}"

    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🛑 Cancel", callback_data="cancel_tasks")]]
    )

    try:
        await status_msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception:
        pass


import pyrogram.utils

# Monkey-patch Pyrogram's hardcoded limits to avoid "Peer id invalid" errors for newer channels
pyrogram.utils.MIN_CHANNEL_ID = -100999999999999
pyrogram.utils.MIN_CHAT_ID = -9999999999999

# Initialize bot client
# in_memory=True prevents SQLite DB creation/writes for peer caches which saves some background RAM/IO
app = Client(
    "terabox_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    await db.add_user(user_id)
    await message.reply_text(
        "🎉 Welcome! I am a high-speed TeraBox downloader bot.\n\n"
        "🔗 Send me a TeraBox link and I'll securely download and send you the file directly here.\n"
        "🛑 Use /cancel to stop all your active downloads.\n"
        "🌐 Supported domains: terabox.com, teraboxapp.com, etc."
    )

@app.on_message(filters.command("block") & filters.user(OWNER_ID) if OWNER_ID else filters.command("block") & filters.user([]))
async def block_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /block <user_id>")
    try:
        user_id = int(message.command[1])
        await db.block_user(user_id)
        await message.reply_text(f"User {user_id} blocked successfully.")
    except ValueError:
        await message.reply_text("Invalid user ID.")

@app.on_message(filters.command("unblock") & filters.user(OWNER_ID) if OWNER_ID else filters.command("unblock") & filters.user([]))
async def unblock_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /unblock <user_id>")
    try:
        user_id = int(message.command[1])
        await db.unblock_user(user_id)
        await message.reply_text(f"User {user_id} unblocked successfully.")
    except ValueError:
        await message.reply_text("Invalid user ID.")

@app.on_message(filters.command("approve") & filters.user(OWNER_ID) if OWNER_ID else filters.command("approve") & filters.user([]))
async def approve_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /approve <user_id>")
    try:
        user_id = int(message.command[1])
        await db.approve_user(user_id)
        await message.reply_text(f"User {user_id} approved successfully. They now have no limits.")
    except ValueError:
        await message.reply_text("Invalid user ID.")

@app.on_message(filters.command("disapprove") & filters.user(OWNER_ID) if OWNER_ID else filters.command("disapprove") & filters.user([]))
async def disapprove_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /disapprove <user_id>")
    try:
        user_id = int(message.command[1])
        await db.disapprove_user(user_id)
        await message.reply_text(f"User {user_id} disapproved successfully. They are back to normal limits.")
    except ValueError:
        await message.reply_text("Invalid user ID.")

@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID) if OWNER_ID else filters.command("broadcast") & filters.user([]))
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

@app.on_message(filters.command("setmax") & filters.user(OWNER_ID) if OWNER_ID else filters.command("setmax") & filters.user([]))
async def setmax_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /setmax <size_in_MB>")
    try:
        max_mb = float(message.command[1])
        await db.update_settings("max_file_size_bytes", max_mb * 1024 * 1024)
        await message.reply_text(f"Max file size set to {max_mb:.2f} MB.")
    except ValueError:
        await message.reply_text("Invalid size value.")

@app.on_message(filters.command("setmin") & filters.user(OWNER_ID) if OWNER_ID else filters.command("setmin") & filters.user([]))
async def setmin_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /setmin <size_in_MB>")
    try:
        min_mb = float(message.command[1])
        await db.update_settings("min_file_size_bytes", min_mb * 1024 * 1024)
        await message.reply_text(f"Min file size set to {min_mb:.2f} MB.")
    except ValueError:
        await message.reply_text("Invalid size value.")

@app.on_message(filters.command("setlimit") & filters.user(OWNER_ID) if OWNER_ID else filters.command("setlimit") & filters.user([]))
async def setlimit_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /setlimit <number_of_links>")
    try:
        limit = int(message.command[1])
        await db.update_settings("daily_limit", limit)
        await message.reply_text(f"Daily download limit set to {limit} links.")
    except ValueError:
        await message.reply_text("Invalid limit value.")

@app.on_message(filters.command("settings") & filters.user(OWNER_ID) if OWNER_ID else filters.command("settings") & filters.user([]))
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

@app.on_message(filters.command("log") & filters.user(OWNER_ID) if OWNER_ID else filters.command("log") & filters.user([]))
async def log_command(client: Client, message: Message):
    if os.path.exists("bot.log"):
        await message.reply_document("bot.log")
    else:
        await message.reply_text("Log file not found.")

@app.on_message(filters.command("cancel"))
async def cancel_command(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in user_tasks and user_tasks[user_id]:
        for task in user_tasks[user_id]:
            task.cancel()
        user_tasks[user_id] = []
        await message.reply_text("🛑 <b>All your tasks have been cancelled.</b>", parse_mode=ParseMode.HTML)
    else:
        await message.reply_text("You have no running tasks.")

@app.on_callback_query(filters.regex("^cancel_tasks$"))
async def cancel_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id in user_tasks and user_tasks[user_id]:
        for task in user_tasks[user_id]:
            task.cancel()
        user_tasks[user_id] = []
        await callback_query.message.edit_text("🛑 <b>Task Cancelled.</b>", parse_mode=ParseMode.HTML)
    else:
        await callback_query.answer("No running tasks to cancel.", show_alert=True)

@app.on_message(filters.text & filters.regex(r"http[s]?://[^\s]+"))
async def handle_link(client: Client, message: Message):
    user_id = message.from_user.id

    # Check block status
    user = await db.get_user(user_id)
    if user and user.get("is_blocked"):
        return await message.reply_text("❌ You are blocked from using this bot.")

    # Check limit
    allowed = await db.check_and_update_limit(user_id)
    if not allowed:
        return await message.reply_text("❌ You have reached your daily limit of 10 links. Please try again tomorrow or contact the owner.")

    current_task = asyncio.current_task()

    if user_id not in user_tasks:
        user_tasks[user_id] = []
    user_tasks[user_id].append(current_task)

    # Extract url and optional password (e.g., "https://terabox.com/s/123 mypass")
    parts = message.text.split(maxsplit=1)
    url = parts[0]
    password = parts[1] if len(parts) > 1 else ""

    # Simple check if url contains terabox
    if "tera" not in url.lower() and "1024" not in url.lower():
        if current_task in user_tasks[user_id]:
            user_tasks[user_id].remove(current_task)
        return

    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🛑 Cancel", callback_data="cancel_tasks")]]
    )

    is_group = message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]

    if is_group:
        try:
            # First check if we can DM the user by sending a silent typing action
            await client.send_chat_action(
                chat_id=user_id,
                action=ChatAction.TYPING
            )
        except Exception as e:
            bot_username = (await client.get_me()).username
            await message.reply_text(
                f"❌ Please start me in DM first to process your link: [Start Bot](https://t.me/{bot_username}?start=1)",
                disable_web_page_preview=True,
                parse_mode=ParseMode.MARKDOWN
            )
            if current_task in user_tasks[user_id]:
                user_tasks[user_id].remove(current_task)
            return

        # Send status message to group instead of the user's DM
        status_msg = await client.send_message(
            chat_id=message.chat.id,
            text=f"🔄 Processing {message.from_user.mention}'s link...",
            disable_web_page_preview=True,
            reply_markup=markup
        )
    else:
        # If it's a DM, reply directly
        status_msg = await message.reply_text(
            "🔄 Processing your link...",
            disable_web_page_preview=True,
            reply_markup=markup
        )

    try:
        async with semaphore:
            # 1. Fetch direct links via external API (using flowapi.py)
            links = None
            try:
                # Offload synchronous requests to a separate thread to not block event loop
                data = await asyncio.to_thread(get_flowvideo_links, url)

                if isinstance(data, dict) and data.get("error"):
                    links = {"error": data.get("error", "Unknown API error")}
                elif "data" in data:
                    # Map flowvideoplayer output structure to bot expected structure
                    links = [
                        {
                            "filename": item.get("file_name", "Unknown"),
                            "size": item.get("file_size", "Unknown"),
                            "direct_link": item.get("download_url") or item.get("stream_final_url"),
                            "thumbnail": item.get("thumbnail")
                        }
                        for item in data["data"]
                    ]
                else:
                    links = {"error": "Invalid API response format"}
            except Exception as e:
                links = {"error": f"Failed to fetch data: {e}"}

            if isinstance(links, dict) and "error" in links:
                error_msg = links.get('error')
                await status_msg.edit_text(f"❌ <b>Error:</b> {error_msg}", parse_mode=ParseMode.HTML)
                return

            if not links:
                await status_msg.edit_text("❌ No files found in this link.")
                return

            total_download_size = 0
            overall_start_time = time.time()

            # 2. Process each file
            for file_info in links:
                direct_link = (file_info.get("direct_link") or file_info.get("download_link") or file_info.get("link") or "")
                direct_link = direct_link.strip()
                if not direct_link:
                    await message.reply_text(
                        f"❌ <b>Could not extract the download link for:</b> {file_info.get('filename', 'Unknown')}\n"
                        "<i>The link may be password-protected, geo-blocked, or the configured cookies have expired.</i>",
                        parse_mode=ParseMode.HTML
                    )
                    continue

                # Parse file size to bytes for limit checking
                size_str = str(file_info.get("size", "0")).upper().strip()
                size_in_bytes = 0
                try:
                    if "GB" in size_str:
                        size_in_bytes = float(size_str.replace("GB", "").strip()) * 1024 * 1024 * 1024
                    elif "MB" in size_str:
                        size_in_bytes = float(size_str.replace("MB", "").strip()) * 1024 * 1024
                    elif "KB" in size_str:
                        size_in_bytes = float(size_str.replace("KB", "").strip()) * 1024
                    elif "B" in size_str:
                        size_in_bytes = float(size_str.replace("B", "").strip())
                    else:
                        size_in_bytes = float(size_str)
                except ValueError:
                    size_in_bytes = 0

                size_allowed, reason = await db.check_file_size_limit(user_id, int(size_in_bytes))
                if not size_allowed:
                    await message.reply_text(
                        f"❌ <b>Limit Exceeded:</b> {file_info.get('filename', 'Unknown')}\n"
                        f"<i>Size ({size_str}) {reason}.</i>\n"
                        "Ask the bot owner to approve you to remove this limit.",
                        parse_mode=ParseMode.HTML
                    )
                    continue

                await status_msg.edit_text(f"📥 Downloading: {file_info.get('filename', 'File')}\nSize: {file_info.get('size', 'Unknown')}")

                # Download and upload file
                direct_link = file_info["direct_link"]
                filename = file_info.get("filename", "downloaded_file")

                # We can stream download to memory if small, or directly pass the url to Pyrogram if supported,
                # but usually Pyrogram doesn't stream from arbitrary URLs with auth.
                # Let's download locally and then upload.

                # Sanitize filename to prevent path traversal
                # The flowvideoplayer API often provides files via .zip download to bypass browser restrictions
                # We should extract the actual filename to remove .zip if it exists for the message
                safe_filename = os.path.basename(filename)

                # The file might be downloaded as a ZIP from the proxy API
                download_is_zip = False
                if direct_link.endswith(".zip") or "file_name=" in direct_link and direct_link.split("file_name=")[-1].endswith(".zip"):
                    download_is_zip = True

                temp_file = f"temp_{message.id}_{safe_filename}"
                temp_file_dl = temp_file + (".zip" if download_is_zip and not temp_file.endswith(".zip") else "")
                temp_thumb = f"thumb_{message.id}.jpg"

                try:
                    download_headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
                        "Accept": "*/*",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Connection": "keep-alive",
                    }

                    start_time = time.time()
                    last_update_time = [0]
                    action_text = f"Downloading: {filename}"

                    # Download main file fast
                    # No cookies are passed, TeraBox direct links usually work without them for the specific short-lived token
                    success = await fast_download(
                        direct_link,
                        download_headers,
                        temp_file_dl,
                        status_msg,
                        action_text,
                        start_time,
                        last_update_time,
                        max_concurrent=20
                    )

                    if not success:
                        await status_msg.edit_text(f"❌ Failed to download {filename}\nMake sure your API server's cookies are valid.")
                        continue

                    # Extract zip if necessary
                    if download_is_zip:
                        await status_msg.edit_text(f"📦 Extracting: {filename}...")
                        import zipfile
                        import tempfile
                        import shutil
                        try:
                            # Offload synchronous unzip to a thread
                            def extract_file():
                                with zipfile.ZipFile(temp_file_dl, 'r') as zip_ref:
                                    # Assume it's a single file archive as packaged by flowvideo
                                    info_list = zip_ref.infolist()
                                    if info_list:
                                        # Create a unique temporary directory to avoid race conditions
                                        with tempfile.TemporaryDirectory() as temp_dir:
                                            extracted_path = zip_ref.extract(info_list[0], path=temp_dir)
                                            # We will use the original filename inside the zip, bypassing any weird '1_' prefixes added by the API
                                            original_filename = os.path.basename(info_list[0].filename)
                                            shutil.move(extracted_path, temp_file)
                                            return original_filename
                                return None

                            extracted_filename = await asyncio.to_thread(extract_file)
                            success = extracted_filename is not None
                            if success:
                                filename = extracted_filename
                            if not success:
                                # Fallback to rename if extraction fails
                                os.rename(temp_file_dl, temp_file)
                            else:
                                # Cleanup original zip
                                os.remove(temp_file_dl)
                        except Exception as e:
                            logger.error(f"Failed to unzip {temp_file_dl}: {e}")
                            # Fallback rename
                            os.rename(temp_file_dl, temp_file)
                    elif temp_file_dl != temp_file:
                        os.rename(temp_file_dl, temp_file)

                    # Download thumbnail if available
                    thumbnail_url = file_info.get("thumbnail")
                    has_thumb = False
                    if thumbnail_url:
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(thumbnail_url, headers=download_headers) as thumb_resp:
                                    if thumb_resp.status == 200:
                                        async with aiofiles.open(temp_thumb, "wb") as tf:
                                            await tf.write(await thumb_resp.read())
                                            has_thumb = True
                        except Exception as e:
                            logger.warning(f"Failed to download thumbnail for {filename}: {e}")

                    await status_msg.edit_text(f"📤 Uploading: {filename}...")


                    # Determine media type for proper upload
                    ext = filename.lower().split('.')[-1] if '.' in filename else ''

                    # Set up caption for dump channel with user info, and a clean caption for the user
                    user_mention = message.from_user.mention
                    user_id_text = f"#ID{message.from_user.id}"

                    dump_caption = (f"📄 File: {filename}\n📦 Size: {file_info.get('size', 'Unknown')}\n"
                                    f"👤 By: {user_mention}\n🆔 {user_id_text}")
                    user_caption = f"📄 File: {filename}\n📦 Size: {file_info.get('size', 'Unknown')}"

                    start_time_upload = time.time()
                    last_update_time_upload = [0]
                    upload_action_text = f"Uploading: {filename}"
                    prog_args = (status_msg, upload_action_text, start_time_upload, last_update_time_upload)

                    kwargs = {
                        "caption": dump_caption if DUMP_CHANNEL_ID else user_caption,
                        "file_name": filename,
                        "progress": progress_bar,
                        "progress_args": prog_args
                    }

                    if has_thumb and os.path.exists(temp_thumb):
                        kwargs["thumb"] = temp_thumb

                    # Target chat for upload is DM (user_id) unless DUMP_CHANNEL_ID is set
                    # If DUMP_CHANNEL_ID is set, it goes there first and is forwarded to DM.
                    target_chat = DUMP_CHANNEL_ID if DUMP_CHANNEL_ID else user_id

                    if ext in ['mp4', 'mkv', 'avi', 'mov', 'webm']:
                        duration = get_video_duration(temp_file)
                        if duration > 0:
                            kwargs["duration"] = duration
                        uploaded_msg = await client.send_video(chat_id=target_chat, video=temp_file, **kwargs)
                    elif ext in ['jpg', 'jpeg', 'png', 'webp']:
                        # send_photo does not support file_name parameter in Pyrogram
                        photo_kwargs = kwargs.copy()
                        photo_kwargs.pop("file_name", None)
                        photo_kwargs.pop("thumb", None) # send_photo uses photo directly, no thumb param
                        uploaded_msg = await client.send_photo(chat_id=target_chat, photo=temp_file, **photo_kwargs)
                    elif ext in ['mp3', 'm4a', 'flac', 'wav']:
                        uploaded_msg = await client.send_audio(chat_id=target_chat, audio=temp_file, **kwargs)
                    else:
                        uploaded_msg = await client.send_document(chat_id=target_chat, document=temp_file, **kwargs)

                    # Forward to user if sent to dump channel
                    if DUMP_CHANNEL_ID:
                        await uploaded_msg.copy(user_id, caption=user_caption)
                finally:
                    # Cleanup temp file
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                    if 'temp_file_dl' in locals() and os.path.exists(temp_file_dl):
                        os.remove(temp_file_dl)
                    if os.path.exists(temp_thumb):
                        os.remove(temp_thumb)

                    if success:
                        total_download_size += size_in_bytes

            overall_end_time = time.time()
            total_time_taken = overall_end_time - overall_start_time

            stats_msg = (
                f"✅ **Task Completed Successfully**\n\n"
                f"📦 **Total Size:** {format_bytes(total_download_size)}\n"
                f"⏱ **Time Taken:** {format_time(total_time_taken)}"
            )

            # Delete the status update message and send the stats message to chat
            await status_msg.delete()
            if is_group:
                await client.send_message(
                    chat_id=message.chat.id,
                    text=stats_msg,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await message.reply_text(stats_msg, parse_mode=ParseMode.MARKDOWN)

    except asyncio.CancelledError:
        logger.info(f"Task for user {user_id} was cancelled.")
        await status_msg.edit_text("🛑 <b>Task Cancelled.</b>", parse_mode=ParseMode.HTML)
    except FloodWait as e:
        logger.warning(f"FloodWait encountered: sleeping for {e.value} seconds.")
        await status_msg.edit_text(f"⏳ Rate limited by Telegram. Waiting for {e.value} seconds...")
        await asyncio.sleep(e.value)
        await status_msg.edit_text("🔄 Retrying...")
        # Ideally retry logic should be implemented, but sleeping is a start
    except Exception as e:
        logger.error(f"Error processing {url}: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ An unexpected error occurred.")
    finally:
        if current_task in user_tasks[user_id]:
            user_tasks[user_id].remove(current_task)
        if is_group:
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Could not delete original link message in group: {e}")

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
                import pyrogram.utils

                channel_id = pyrogram.utils.get_channel_id(DUMP_CHANNEL_ID)
                # For bots that are admins of the channel, access_hash=0 is allowed to fetch channel info
                await app.invoke(GetChannels(id=[InputChannel(channel_id=channel_id, access_hash=0)]))

                # Fetch again now that Pyrogram has cached the peer from the raw response
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
