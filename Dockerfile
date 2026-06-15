FROM ubuntu:24.04

# Prevent interactive prompts during apt installations
ENV DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3-pip \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set python3.12 as default
RUN ln -s /usr/bin/python3.12 /usr/bin/python || true

# Copy requirements file
COPY requirements.txt .

# Install python dependencies (using PEP 668 bypass for system python if necessary, or simply pip3)
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy all the rest of the application files
COPY . .

# Run the bot
CMD ["python", "main.py"]
