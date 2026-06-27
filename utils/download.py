import gc
import os
import aiohttp
import aiofiles
import asyncio
from config import logger
from utils.progress import progress_bar

async def ffmpeg_download(url, filepath, status_msg, action_text, start_time, last_update_time):
    """Downloads an m3u8/HLS stream using ffmpeg (renamed to lolas)."""
    try:
        cmd = [
            "lolas",
            "-y",
            "-allowed_extensions", "ALL",
            "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
            "-http_persistent", "1",
            "-http_multiple", "1",
            "-threads", "0",
            "-i", url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            filepath
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Periodically update status while downloading
        async def monitor_process():
            while process.returncode is None:
                # We can't easily get precise progress from ffmpeg without parsing stderr deeply,
                # but we can at least show it's working
                await asyncio.sleep(5)
                try:
                    if os.path.exists(filepath):
                        current_size = os.path.getsize(filepath)
                        # We don't know the total size for m3u8 streams easily, so we just pass 0 for total
                        # to indicate unknown total size, but we can show downloaded size and speed.
                        await progress_bar(current_size, 0, status_msg, action_text, start_time, last_update_time)
                except Exception:
                    pass

        monitor_task = asyncio.create_task(monitor_process())
        stdout, stderr = await process.communicate()
        monitor_task.cancel()

        if process.returncode != 0:
            logger.error(f"ffmpeg failed: {stderr.decode()}")
            return False

        if os.path.exists(filepath):
            return True
        return False

    except Exception as e:
        logger.error(f"ffmpeg_download error: {e}")
        return False


import urllib.parse

async def download_m3u8_concurrently(url, filepath, status_msg, action_text, start_time, last_update_time, max_concurrent=20):
    connector = aiohttp.TCPConnector(limit=max_concurrent)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Fetch playlist
        async with session.get(url) as resp:
            if resp.status != 200:
                return False
            m3u8_content = await resp.text()

        # Parse segments
        segments = []
        lines = m3u8_content.splitlines()
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                # Handle relative URLs
                segment_url = urllib.parse.urljoin(url, line)
                segments.append(segment_url)
                
        if not segments:
            logger.error("No segments found in m3u8")
            return False
            
        total_segments = len(segments)
        segment_files = [f"{filepath}.seg{i}" for i in range(total_segments)]
        downloaded_bytes = [0] * total_segments
        total_size_estimate = 0
        
        # Download segment function
        async def download_segment(i, seg_url):
            retries = 3
            while retries > 0:
                try:
                    async with session.get(seg_url) as seg_resp:
                        if seg_resp.status != 200:
                            retries -= 1
                            await asyncio.sleep(1)
                            continue
                        
                        data = await seg_resp.read()
                        downloaded_bytes[i] = len(data)
                        
                        async with aiofiles.open(segment_files[i], "wb") as sf:
                            await sf.write(data)
                        
                                                # Rough progress update
                        current_total = sum(downloaded_bytes)
                        completed_segments = sum(1 for b in downloaded_bytes if b > 0)
                        if completed_segments > 0:
                            avg_size = current_total / completed_segments
                            estimated_total = int(avg_size * total_segments)
                        else:
                            estimated_total = 0
                        await progress_bar(current_total, estimated_total, status_msg, action_text, start_time, last_update_time)
                        return True
                except Exception as e:
                    retries -= 1
                    await asyncio.sleep(1)
            return False

        # Queue tasks with bounded concurrency
        semaphore = asyncio.Semaphore(max_concurrent)
        async def sem_download(i, seg_url):
            async with semaphore:
                return await download_segment(i, seg_url)

        tasks = [sem_download(i, seg) for i, seg in enumerate(segments)]
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            for sf in segment_files:
                if os.path.exists(sf):
                    os.remove(sf)
            raise
            
        if not all(r is True for r in results if not isinstance(r, Exception)):
            logger.error("Some segments failed to download")
            # Cleanup
            for sf in segment_files:
                if os.path.exists(sf):
                    os.remove(sf)
            return False

        # Merge segments
        async with aiofiles.open(filepath, "wb") as outfile:
            for sf in segment_files:
                if os.path.exists(sf):
                    async with aiofiles.open(sf, "rb") as infile:
                        data = await infile.read()
                        await outfile.write(data)
                    os.remove(sf)
        return True

async def m3u8_download(url, filepath, status_msg, action_text, start_time, last_update_time):
    # Fallback to ffmpeg if the python downloader fails
    success = await download_m3u8_concurrently(url, filepath, status_msg, action_text, start_time, last_update_time)
    if success:
        return True
    return await ffmpeg_download(url, filepath, status_msg, action_text, start_time, last_update_time)

async def fast_download(url, headers, filepath, status_msg, action_text, start_time, last_update_time, max_concurrent=10):
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
                                    if len(buffer) >= 1024 * 1024:
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
                            chunk = await infile.read(2 * 1024 * 1024)
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

                        if len(buffer) >= 1024 * 1024:
                            await f.write(buffer)
                            buffer.clear()

                        if total_size > 0:
                            await progress_bar(downloaded, total_size, status_msg, action_text, start_time, last_update_time)
                return True
