import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "/data/db/sync.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                docs_processed INTEGER DEFAULT 0,
                docs_failed INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running'
            );

            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                last_modified TEXT NOT NULL,
                page_count INTEGER,
                sync_status TEXT DEFAULT 'pending',
                output_path TEXT,
                synced_at TEXT,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        conn.execute(
            "INSERT OR IGNORE INTO settings VALUES ('poll_interval_minutes', ?)",
            (os.environ.get("POLL_INTERVAL_MINUTES", "15"),)
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings VALUES ('ocr_enabled', ?)",
            (os.environ.get("OCR_ENABLED", "true"),)
        )
        conn.commit()


def get_setting(key):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, str(value)))
        conn.commit()


def document_needs_sync(doc_id, last_modified):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT last_modified, sync_status FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        if not row:
            return True
        if row["sync_status"] != "synced":
            return True
        return row["last_modified"] != last_modified


def upsert_document(doc_id, title, last_modified):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO documents (id, title, last_modified)
            VALUES (?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                last_modified=excluded.last_modified
        """, (doc_id, title, last_modified))
        conn.commit()


def mark_document_synced(doc_id, output_path, page_count):
    with get_conn() as conn:
        conn.execute("""
            UPDATE documents
            SET sync_status='synced', output_path=?, page_count=?, synced_at=?, error=NULL
            WHERE id=?
        """, (output_path, page_count, datetime.utcnow().isoformat(), doc_id))
        conn.commit()


def mark_document_failed(doc_id, error):
    with get_conn() as conn:
        conn.execute("""
            UPDATE documents
            SET sync_status='failed', error=?, synced_at=?
            WHERE id=?
        """, (str(error)[:500], datetime.utcnow().isoformat(), doc_id))
        conn.commit()


def create_sync_run():
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sync_runs (started_at, status) VALUES (?,?)",
            (datetime.utcnow().isoformat(), "running")
        )
        conn.commit()
        return cur.lastrowid


def finish_sync_run(run_id, docs_processed, docs_failed):
    status = "completed" if docs_failed == 0 else ("failed" if docs_processed == 0 else "partial")
    with get_conn() as conn:
        conn.execute("""
            UPDATE sync_runs
            SET finished_at=?, docs_processed=?, docs_failed=?, status=?
            WHERE id=?
        """, (datetime.utcnow().isoformat(), docs_processed, docs_failed, status, run_id))
        conn.commit()


def get_recent_runs(limit=50):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()]


def get_all_documents():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM documents ORDER BY synced_at DESC"
        ).fetchall()]


def get_stats():
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE sync_status='synced'"
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE sync_status='failed'"
        ).fetchone()[0]
        last_run = conn.execute(
            "SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return {
            "total_synced": total,
            "total_failed": failed,
            "last_run": dict(last_run) if last_run else None,
        }
