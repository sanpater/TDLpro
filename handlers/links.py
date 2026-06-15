import os
import time
import asyncio
import aiohttp
import aiofiles
from pyrogram import Client, filters
from pyrogram.enums import ParseMode, ChatType, ChatAction
from pyrogram.errors import FloodWait
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import user_tasks, semaphore, logger, DUMP_CHANNEL_ID
from core.database import db
from core.flowapi import get_flowvideo_links
from utils.helpers import format_bytes, format_time, get_video_duration
from utils.progress import progress_bar
from utils.download import fast_download, ffmpeg_download

@Client.on_message(filters.text & filters.regex(r"http[s]?://[^\s]+"))
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
                elif "response" in data:
                    # Map flowvideoplayer output structure to bot expected structure
                    links = [
                        {
                            "filename": item.get("file_name", "Unknown"),
                            "size": item.get("file_size", "Unknown"),
                            "direct_link": item.get("fast_stream_url") or item.get("download_url") or item.get("stream_final_url"),
                            "thumbnail": item.get("thumbnail")
                        }
                        for item in data["response"]
                    ]
                elif "data" in data:
                    # Map fallback structure
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

                is_m3u8 = ".m3u8" in direct_link.lower() or "get_m3u8" in direct_link.lower()

                # If it's an m3u8 stream, ensure the target file is an mp4
                if is_m3u8:
                    if not safe_filename.endswith(".mp4"):
                        # strip extension if any and append mp4
                        safe_filename = os.path.splitext(safe_filename)[0] + ".mp4"
                        filename = safe_filename

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
                    if is_m3u8:
                        success = await ffmpeg_download(
                            direct_link,
                            temp_file_dl,
                            status_msg,
                            action_text,
                            start_time,
                            last_update_time
                        )
                    else:
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
