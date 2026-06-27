import time
import asyncio
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils.helpers import format_bytes, format_time

async def progress_bar(current, total, status_msg, action_text, start_time, last_update_time):
    now = time.time()
    # Update every 2 seconds
    if now - last_update_time[0] < 5.0 and current != total:
        return

    last_update_time[0] = now

    is_unknown_total = False
    if total == 0:
        total = 1 # Prevent division by zero
        is_unknown_total = True

    percentage = current * 100 / total
    speed = current / (now - start_time) if now - start_time > 0 else 0
    eta = (total - current) / speed if speed > 0 else 0

    if is_unknown_total:
        progress_str = "[●●●●●●●●●●] ?%\n"
        size_str = f"{format_bytes(current)} / Unknown"
        eta_str = "Unknown"
    else:
        progress_str = "[{0}{1}] {2}%\n".format(
            ''.join(["●" for i in range(int(percentage / 10))]),
            ''.join(["○" for i in range(10 - int(percentage / 10))]),
            round(percentage, 2)
        )
        size_str = f"{format_bytes(current)} / {format_bytes(total)}"
        eta_str = format_time(eta)

    text = f"🔄 <b>{action_text}</b>\n\n"
    text += f"{progress_str}"
    text += f"📦 <b>Size:</b> {size_str}\n"
    text += f"🚀 <b>Speed:</b> {format_bytes(speed)}/s\n"
    text += f"⏳ <b>ETA:</b> {eta_str}"

    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🛑 Cancel", callback_data="cancel_tasks")]]
    )

    try:
        await status_msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception:
        pass
