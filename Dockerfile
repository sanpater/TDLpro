FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install necessary packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Install modern static ffmpeg (Debian's default is too old for required HLS/M3U8 flags)
RUN wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz && \
    tar -xf ffmpeg-release-amd64-static.tar.xz && \
    mv ffmpeg-*/ffmpeg /usr/local/bin/ && \
    mv ffmpeg-*/ffprobe /usr/local/bin/ && \
    rm -rf ffmpeg-release-amd64-static.tar.xz ffmpeg-*

# Copy requirements file
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all the rest of the application files
COPY . .

# Run the bot
CMD ["python", "main.py"]
