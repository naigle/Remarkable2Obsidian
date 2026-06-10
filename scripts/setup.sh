#!/usr/bin/env bash
set -e

echo "=== reMarkable Sync — first-time setup ==="
echo

# 1. Create data dirs
echo "[1/4] Creating data directories..."
mkdir -p data/{converted,db,rmapi-config,rclone-config,hf-cache}

# 2. .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "[2/4] Created .env from example — edit it now if needed"
else
  echo "[2/4] .env already exists, skipping"
fi

# 3. Build images
echo "[3/4] Building Docker images (this takes a few minutes on first run)..."
docker compose build

# 4. Auth
echo
echo "[4/4] Authentication"
echo
echo "--- reMarkable Cloud ---"
echo "Run the following and follow the prompts (one-time device registration):"
echo
echo "  docker compose run --rm sync rmapi"
echo
echo "--- Google Drive (rclone) ---"
echo "Run the following — it will open a browser for OAuth:"
echo
echo "  docker compose run --rm -p 53682:53682 sync rclone config"
echo
echo "  When prompted:"
echo "  - New remote name: gdrive"
echo "  - Storage type: drive"
echo "  - Scope: drive (full access)"
echo "  - Use auto config: yes"
echo
echo "=== Setup complete ==="
echo "Start the service with: docker compose up -d"
echo "Dashboard at: http://localhost:${WEB_PORT:-8080}"
