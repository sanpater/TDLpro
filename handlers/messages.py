import asyncio
import os
import time
import aiohttp
import aiofiles
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode, ChatType, ChatAction
from pyrogram.errors import FloodWait

from core.config import DUMP_CHANNEL_ID
from core.state import user_tasks, semaphore
from database.db import db
from api.flow import get_flowvideo_links
from utils.helpers import format_bytes, format_time, get_video_duration
from utils.download import fast_download, progress_bar

logger = logging.getLogger(__name__)

def register_message_handlers(app: Client):
    @app.on_message(filters.text & filters.regex(r"http[s]?://[^\s]+"))
    async def handle_link(client: Client, message: Message):
        user_id = message.from_user.id

        user = await db.get_user(user_id)
        if user and user.get("is_blocked"):
            return await message.reply_text("❌ You are blocked from using this bot.")

        allowed = await db.check_and_update_limit(user_id)
        if not allowed:
            return await message.reply_text("❌ You have reached your daily limit. Please try again tomorrow or contact the owner.")

        current_task = asyncio.current_task()

        if user_id not in user_tasks:
            user_tasks[user_id] = []
        user_tasks[user_id].append(current_task)

        parts = message.text.split(maxsplit=1)
        url = parts[0]

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

            status_msg = await client.send_message(
                chat_id=message.chat.id,
                text=f"🔄 Processing {message.from_user.mention}'s link...",
                disable_web_page_preview=True,
                reply_markup=markup
            )
        else:
            status_msg = await message.reply_text(
                "🔄 Processing your link...",
                disable_web_page_preview=True,
                reply_markup=markup
            )

        try:
            async with semaphore:
                links = None
                try:
                    data = await asyncio.to_thread(get_flowvideo_links, url)

                    if isinstance(data, dict) and data.get("error"):
                        links = {"error": data.get("error", "Unknown API error")}
                    elif "response" in data:
                        links = []
                        for item in data["response"]:
                            dl_url = item.get("fast_stream_url") or item.get("download_url") or item.get("stream_final_url")
                            links.append({
                                "filename": item.get("file_name", "Unknown"),
                                "size": item.get("file_size", "Unknown"),
                                "size_bytes": item.get("file_size_bytes", 0),
                                "direct_link": dl_url,
                                "thumbnail": item.get("thumbnail")
                            })
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

                for file_info in links:
                    direct_link = file_info.get("direct_link", "").strip()
                    if not direct_link:
                        await message.reply_text(
                            f"❌ <b>Could not extract the download link for:</b> {file_info.get('filename', 'Unknown')}\n"
                            "<i>The link may be password-protected, geo-blocked, or expired.</i>",
                            parse_mode=ParseMode.HTML
                        )
                        continue

                    size_in_bytes = file_info.get("size_bytes", 0)
                    size_allowed, reason = await db.check_file_size_limit(user_id, int(size_in_bytes))
                    if not size_allowed:
                        await message.reply_text(
                            f"❌ <b>Limit Exceeded:</b> {file_info.get('filename', 'Unknown')}\n"
                            f"<i>Size {reason}.</i>\n"
                            "Ask the bot owner to approve you to remove this limit.",
                            parse_mode=ParseMode.HTML
                        )
                        continue

                    await status_msg.edit_text(f"📥 Downloading: {file_info.get('filename', 'File')}\nSize: {file_info.get('size', 'Unknown')}")

                    filename = file_info.get("filename", "downloaded_file")
                    safe_filename = os.path.basename(filename)

                    if not safe_filename.endswith(('.mp4', '.mkv', '.avi', '.zip')):
                        safe_filename += '.mp4'

                    temp_file = f"temp_{message.id}_{safe_filename}"
                    temp_thumb = f"thumb_{message.id}.jpg"
                    success = False

                    try:
                        start_time = time.time()
                        last_update_time = [0]
                        action_text = f"Downloading: {filename}"

                        if ".m3u8" in direct_link or "m3u8" in direct_link.lower() or "my-streaming" in direct_link:
                            await status_msg.edit_text(f"📥 Downloading Stream: {filename}\nThis might take a while...")
                            process = await asyncio.create_subprocess_exec(
                                "ffmpeg", "-y", "-i", direct_link, "-c", "copy", "-bsf:a", "aac_adtstoasc", temp_file,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE
                            )
                            while process.returncode is None:
                                await asyncio.sleep(2)
                                await progress_bar(0, 1, status_msg, "Downloading HLS Stream...", start_time, last_update_time)

                            _, stderr = await process.communicate()
                            if process.returncode == 0:
                                success = True
                            else:
                                logger.error(f"FFMPEG failed: {stderr.decode()}")
                                success = False
                        else:
                            download_headers = {
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                "Accept": "*/*",
                                "Accept-Language": "en-US,en;q=0.9",
                                "Connection": "keep-alive",
                            }
                            success = await fast_download(
                                direct_link,
                                download_headers,
                                temp_file,
                                status_msg,
                                action_text,
                                start_time,
                                last_update_time,
                                max_concurrent=20
                            )

                        if not success:
                            await status_msg.edit_text(f"❌ Failed to download {filename}")
                            continue

                        thumbnail_url = file_info.get("thumbnail")
                        has_thumb = False
                        if thumbnail_url:
                            try:
                                async with aiohttp.ClientSession() as session:
                                    async with session.get(thumbnail_url) as thumb_resp:
                                        if thumb_resp.status == 200:
                                            async with aiofiles.open(temp_thumb, "wb") as tf:
                                                await tf.write(await thumb_resp.read())
                                                has_thumb = True
                            except Exception as e:
                                logger.warning(f"Failed to download thumbnail for {filename}: {e}")

                        await status_msg.edit_text(f"📤 Uploading: {filename}...")

                        ext = temp_file.lower().split('.')[-1]

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
                            "file_name": safe_filename,
                            "progress": progress_bar,
                            "progress_args": prog_args
                        }

                        if has_thumb and os.path.exists(temp_thumb):
                            kwargs["thumb"] = temp_thumb

                        target_chat = DUMP_CHANNEL_ID if DUMP_CHANNEL_ID else user_id

                        if ext in ['mp4', 'mkv', 'avi', 'mov', 'webm']:
                            duration = get_video_duration(temp_file)
                            if duration > 0:
                                kwargs["duration"] = duration
                            uploaded_msg = await client.send_video(chat_id=target_chat, video=temp_file, **kwargs)
                        elif ext in ['jpg', 'jpeg', 'png', 'webp']:
                            photo_kwargs = kwargs.copy()
                            photo_kwargs.pop("file_name", None)
                            photo_kwargs.pop("thumb", None)
                            uploaded_msg = await client.send_photo(chat_id=target_chat, photo=temp_file, **photo_kwargs)
                        elif ext in ['mp3', 'm4a', 'flac', 'wav']:
                            uploaded_msg = await client.send_audio(chat_id=target_chat, audio=temp_file, **kwargs)
                        else:
                            uploaded_msg = await client.send_document(chat_id=target_chat, document=temp_file, **kwargs)

                        if DUMP_CHANNEL_ID:
                            await uploaded_msg.copy(user_id, caption=user_caption)
                    finally:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
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
