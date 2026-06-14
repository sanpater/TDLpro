import asyncio
import aiohttp
import aiofiles
import time
import logging
import os
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait

from utils.helpers import format_bytes, format_time

logger = logging.getLogger(__name__)

async def fast_download(url, headers, filepath, status_msg, action_text, start_time, last_update_time, max_concurrent=20):
    connector = aiohttp.TCPConnector(limit=max_concurrent)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.head(url, headers=headers, allow_redirects=True) as resp:
            total_size = int(resp.headers.get("content-length", 0))
            accept_ranges = resp.headers.get("accept-ranges", "none")

        if total_size > 0 and accept_ranges == "bytes":
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

                                    if len(buffer) >= 2 * 1024 * 1024:
                                        await f.write(buffer)
                                        buffer.clear()

                                    total_downloaded = sum(downloaded)
                                    await progress_bar(total_downloaded, total_size, status_msg, action_text, start_time, last_update_time)

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
    if now - last_update_time[0] < 3.0 and current != total:
        return

    last_update_time[0] = now

    if total == 0:
        total = 1

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
