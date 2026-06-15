FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install necessary packages (like ffmpeg for video duration and extraction)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all the rest of the application files
COPY . .

# Run the bot
CMD ["python", "main.py"]
