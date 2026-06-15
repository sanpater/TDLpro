import asyncio
from utils.download import ffmpeg_download
from config import logger

class MockMsg:
    async def edit_text(self, text, parse_mode=None, reply_markup=None):
        pass

async def test():
    await ffmpeg_download("dummy", "dummy", MockMsg(), "dummy", 0, [0])

# asyncio.run(test())
