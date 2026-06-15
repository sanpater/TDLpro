import subprocess
from hachoir.parser import createParser
from hachoir.metadata import extractMetadata
from config import logger

def format_bytes(size):
    size = int(size)
    power = 2**10
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}B"

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
