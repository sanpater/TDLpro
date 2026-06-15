import time
import asyncio
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils.helpers import format_bytes, format_time

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
