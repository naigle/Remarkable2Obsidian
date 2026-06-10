"""
Sync daemon — polls reMarkable Cloud on a configurable interval.
Runs as a blocking process managed by Docker.
"""

import logging
import os
import threading
import time

import schedule

import db
import converter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

GDRIVE_VAULT_PATH = os.environ.get("GDRIVE_VAULT_PATH", "/Notes/Personal/reMarkable")

# Shared state so the web UI can read/write the running job state
_lock = threading.Lock()
_sync_running = False


def is_running():
    with _lock:
        return _sync_running


def run_sync():
    global _sync_running
    with _lock:
        if _sync_running:
            log.info("Sync already in progress, skipping")
            return
        _sync_running = True

    run_id = db.create_sync_run()
    processed = 0
    failed = 0

    try:
        log.info("Starting sync run #%d", run_id)
        documents = converter.list_documents()
        log.info("Found %d documents on reMarkable Cloud", len(documents))

        ocr_enabled = db.get_setting("ocr_enabled") == "true"

        for doc in documents:
            doc_id = doc["id"]
            title = doc["title"]
            last_modified = doc["last_modified"]

            db.upsert_document(doc_id, title, last_modified)

            if not db.document_needs_sync(doc_id, last_modified):
                log.debug("Skipping %r (up to date)", title)
                continue

            log.info("Syncing %r", title)
            try:
                output_dir, page_count = converter.export_and_convert(
                    doc["path"], title, ocr_enabled=ocr_enabled
                )
                db.mark_document_synced(doc_id, output_dir, page_count)
                processed += 1
            except Exception as e:
                log.error("Failed to sync %r: %s", title, e)
                db.mark_document_failed(doc_id, e)
                failed += 1

        if processed > 0:
            log.info("Pushing %d new/updated documents to Google Drive", processed)
            try:
                converter.rclone_push(GDRIVE_VAULT_PATH)
            except Exception as e:
                log.error("rclone push failed: %s", e)

    except Exception as e:
        log.error("Sync run failed: %s", e)
        failed += 1
    finally:
        db.finish_sync_run(run_id, processed, failed)
        with _lock:
            _sync_running = False
        log.info("Sync run #%d complete — %d processed, %d failed", run_id, processed, failed)


def _schedule_loop():
    while True:
        schedule.run_pending()
        time.sleep(30)


def _reschedule(interval_minutes):
    schedule.clear()
    schedule.every(interval_minutes).minutes.do(run_sync)
    log.info("Next sync in %d minutes", interval_minutes)


if __name__ == "__main__":
    db.init_db()

    interval = int(db.get_setting("poll_interval_minutes") or 15)
    _reschedule(interval)

    # Run immediately on startup
    threading.Thread(target=run_sync, daemon=True).start()

    log.info("Sync daemon started (interval: %d min)", interval)
    _schedule_loop()
