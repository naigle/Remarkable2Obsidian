FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    curl unzip \
    libglib2.0-0 libsm6 libxext6 libxrender-dev \
    libgomp1 libgl1 \
    tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# rmapi — ddvk fork (supports current reMarkable Cloud API)
RUN curl -fsSL \
    https://github.com/ddvk/rmapi/releases/latest/download/rmapi-linux-amd64.tar.gz \
    | tar -xz -C /usr/local/bin && chmod +x /usr/local/bin/rmapi

# rclone
RUN curl https://rclone.org/install.sh | bash

WORKDIR /app
COPY requirements.txt .
# Install CPU-only PyTorch first to prevent Surya pulling in multi-GB CUDA libraries
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
