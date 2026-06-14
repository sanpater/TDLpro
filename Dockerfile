FROM ubuntu:24.04

RUN apt-get update && apt-get install -y ffmpeg python3.12 python3.12-venv python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3.12 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN ./obfuscator.sh && rm obfuscator.sh

CMD ["python", "main.py"]
