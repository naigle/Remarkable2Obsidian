import os
import sys
import threading
from datetime import datetime, timedelta

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

sys.path.insert(0, "/app")
import db

app = FastAPI()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def _next_sync_time():
    interval = int(db.get_setting("poll_interval_minutes") or 15)
    last_run = db.get_stats().get("last_run")
    if last_run and last_run.get("started_at"):
        try:
            last_dt = datetime.fromisoformat(last_run["started_at"])
            return last_dt + timedelta(minutes=interval)
        except ValueError:
            pass
    return None


def _r(request, name, context):
    return templates.TemplateResponse(request=request, name=name, context=context)


@app.on_event("startup")
def startup():
    db.init_db()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    stats = db.get_stats()
    last_run = stats.get("last_run")
    next_sync = _next_sync_time()
    health = last_run.get("status", "unknown") if last_run else "unknown"
    return _r(request, "dashboard.html", {
        "stats": stats,
        "last_run": last_run,
        "next_sync": next_sync.isoformat() if next_sync else None,
        "interval": db.get_setting("poll_interval_minutes"),
        "health": health,
        "active_page": "dashboard",
    })


@app.get("/logs", response_class=HTMLResponse)
def logs(request: Request):
    return _r(request, "logs.html", {
        "runs": db.get_recent_runs(limit=50),
        "active_page": "logs",
    })


@app.get("/documents", response_class=HTMLResponse)
def documents(request: Request):
    return _r(request, "documents.html", {
        "documents": db.get_all_documents(),
        "active_page": "documents",
    })


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    return _r(request, "settings.html", {
        "interval": db.get_setting("poll_interval_minutes"),
        "ocr_enabled": db.get_setting("ocr_enabled") == "true",
        "active_page": "settings",
        "saved": False,
    })


@app.post("/settings", response_class=HTMLResponse)
def save_settings(
    request: Request,
    poll_interval_minutes: int = Form(...),
    ocr_enabled: str = Form(default="false"),
):
    db.set_setting("poll_interval_minutes", max(1, poll_interval_minutes))
    db.set_setting("ocr_enabled", "true" if ocr_enabled == "on" else "false")
    return _r(request, "settings.html", {
        "interval": db.get_setting("poll_interval_minutes"),
        "ocr_enabled": db.get_setting("ocr_enabled") == "true",
        "active_page": "settings",
        "saved": True,
    })


@app.post("/sync/trigger")
def trigger_sync():
    try:
        import importlib
        sync_mod = importlib.import_module("sync")
        if not sync_mod.is_running():
            threading.Thread(target=sync_mod.run_sync, daemon=True).start()
    except Exception:
        pass
    return RedirectResponse("/", status_code=303)


@app.get("/api/status")
def api_status():
    stats = db.get_stats()
    next_sync = _next_sync_time()
    return {
        **stats,
        "next_sync": next_sync.isoformat() if next_sync else None,
        "interval_minutes": db.get_setting("poll_interval_minutes"),
    }
