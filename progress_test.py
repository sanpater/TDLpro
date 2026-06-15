import asyncio
from utils.progress import progress_bar
import time

class MockMsg:
    async def edit_text(self, text, parse_mode=None, reply_markup=None):
        print(text)

async def test():
    msg = MockMsg()
    start_time = time.time() - 10
    last_update_time = [0]
    await progress_bar(5000000, 0, msg, "Downloading (m3u8)", start_time, last_update_time)

asyncio.run(test())
