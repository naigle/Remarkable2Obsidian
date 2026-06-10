FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    curl \
    libglib2.0-0 libsm6 libxext6 libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# rmapi — reMarkable Cloud CLI
RUN curl -fsSL \
    https://github.com/juruen/rmapi/releases/latest/download/rmapi-linux-amd64.tar.gz \
    | tar -xz -C /usr/local/bin && chmod +x /usr/local/bin/rmapi

# rclone
RUN curl https://rclone.org/install.sh | bash

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
