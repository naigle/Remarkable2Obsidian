# Remarkable2Obsidian

Self-hosted service that syncs reMarkable Cloud notebooks to an Obsidian vault on Google Drive.

Runs on a Proxmox VM (Debian 12 + Docker Compose). Notebooks are downloaded, rendered to PNG images, and written as Markdown files — ready to open in Obsidian.

## Architecture

```
reMarkable Cloud
      │  rmapi (ddvk fork)
      ▼
sync daemon  ──→  .rmdoc download
                  │  rmscene render
                  ▼
             PNG images + Markdown
                  │  rclone sync
                  ▼
         gdrive:Notes/Personal/reMarkable
                  │
                  ▼
         Obsidian vault (Google Drive)

Web dashboard  ─→  http://<vm-ip>:8080
```

## Stack

| Component | Technology |
|-----------|-----------|
| reMarkable API | [ddvk/rmapi](https://github.com/ddvk/rmapi) |
| Stroke rendering | [rmscene](https://github.com/ricklupton/rmscene) + Pillow |
| Google Drive sync | rclone |
| Web dashboard | FastAPI + Jinja2 + htmx |
| Database | SQLite |
| Container | Docker Compose |

## VM Setup

Proxmox VM spec:
- OS: Debian 12
- Machine type: q35, CPU: Host
- 2 vCPU, 2 GB RAM, 30 GB disk
- Disk cache: Write Through

After provisioning:
```bash
# Grow partition if needed
growpart /dev/sda 1 && resize2fs /dev/sda1

# Install Docker
curl -fsSL https://get.docker.com | sh

# Enable networking persistence
systemctl enable systemd-networkd systemd-resolved
```

## Installation

```bash
git clone https://github.com/naigle/Remarkable2Obsidian.git /opt/remarkable-sync
cd /opt/remarkable-sync
docker compose build
```

## Authentication

### reMarkable Cloud (rmapi)

Uses the ddvk fork — required for Google OAuth reMarkable accounts:

```bash
docker compose run --rm sync rmapi
# Follow the device registration URL printed to stdout
```

Config is stored in `data/rmapi-config/rmapi.conf`.

### Google Drive (rclone)

```bash
docker compose run --rm sync rclone config
# Create a new remote named "gdrive", type "drive"
# Complete OAuth flow in browser
```

Config is stored in `data/rclone-config/rclone.conf`.

## Running

```bash
docker compose up -d
```

Dashboard available at `http://<vm-ip>:8080`.

## Data layout

```
data/
  converted/        # Rendered PNG + Markdown output
  db/sync.db        # SQLite — documents, sync runs, settings
  rmapi-config/     # reMarkable auth token
  rclone-config/    # Google Drive OAuth token
  hf-cache/         # (unused, kept for future model use)
```

## Known limitations

- Notebooks with ` / ` in the title fail to download (rmapi path parsing limitation) — rename on the reMarkable device to fix
- Trashed notebooks appear in `rmapi find /` output but cannot be fetched — harmless errors
- PDF/EPUB imports show 0 pages (no stroke data to render — expected)
- OCR is disabled by default; Tesseract quality on handwriting is poor

## Settings

Accessible via the dashboard at `/settings`:

| Setting | Default | Description |
|---------|---------|-------------|
| Poll interval | 60 min | How often to check reMarkable Cloud |
| OCR | Off | Tesseract text extraction under each page image |
