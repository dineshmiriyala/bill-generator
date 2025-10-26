# --- 🔹 Automatic Sync Event Listeners for Cloud Staging ---
from sqlalchemy.orm import Session
from sqlalchemy import event
from datetime import datetime, date
from pathlib import Path
import os, json, sys

# Define tables to be tracked
SYNCED_TABLES = {"customer", "invoice", "item", "invoice_item"}
APP_NAME = "SLO BILL"

# ---------------- PATH LOGIC ----------------
def _desktop_data_dir(app_name: str) -> Path:
    """Cross-platform base data directory for app storage."""
    if os.name == "nt":  # Windows
        return Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / app_name
    elif sys.platform == "darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / app_name
    else:  # Linux
        return Path.home() / ".local" / "share" / app_name

def get_sync_folder() -> Path:
    """Return correct sync staging folder path depending on environment."""
    is_desktop = os.getenv("BG_DESKTOP") == "1"
    if is_desktop:
        folder = _desktop_data_dir(APP_NAME) / "logs" / "sync_staging"
    else:
        folder = Path("logs") / "sync_staging"

    folder.mkdir(parents=True, exist_ok=True)
    return folder

# ---------------- LOGGING HELPERS ----------------
def stage_sync(table, action, data):
    """Save change as JSON to logs/sync_staging/ for later Supabase sync."""
    if table not in SYNCED_TABLES:
        return  # skip non-core tables

    folder = get_sync_folder()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{table}_{action}_{timestamp}.json"
    filepath = folder / filename

    payload = {
        "table": table,
        "action": action,
        "timestamp": datetime.now().isoformat(),
        "data": data
    }

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"[staged ✅] {table} {action} → {filename}")
    except Exception as e:
        print(f"[staging ⚠️] Failed to log {table} {action}: {e}")

def obj_to_dict(obj):
    """Convert SQLAlchemy ORM object to JSON-safe dict."""
    result = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name, None)
        if isinstance(val, (datetime, date)):
            result[col.name] = val.isoformat()  # ✅ serialize datetime/date
        else:
            result[col.name] = val
    return result

# ---------------- EVENT LISTENERS ----------------
@event.listens_for(Session, "after_flush")
def track_local_db_changes(session, flush_context):
    """Track inserts, updates, deletes automatically."""
    for obj in list(session.new):
        table = getattr(obj.__table__, "name", None)
        if table in SYNCED_TABLES:
            stage_sync(table, "insert", obj_to_dict(obj))

    for obj in list(session.dirty):
        table = getattr(obj.__table__, "name", None)
        if table in SYNCED_TABLES and session.is_modified(obj, include_collections=False):
            stage_sync(table, "update", obj_to_dict(obj))

    for obj in list(session.deleted):
        table = getattr(obj.__table__, "name", None)
        if table in SYNCED_TABLES:
            stage_sync(table, "delete", obj_to_dict(obj))

# ---------------- NEW: AFTER COMMIT LISTENER ----------------
@event.listens_for(Session, "after_commit")
def track_after_commit(session):
    """Ensure all related or dependent inserts (like invoiceItems) are logged post-commit."""
    try:
        all_objects = getattr(session, "new", [])
        for obj in list(all_objects):
            table = getattr(obj.__table__, "name", None)
            if table in SYNCED_TABLES:
                stage_sync(table, "post_commit_insert", obj_to_dict(obj))
    except Exception as e:
        print(f"[after_commit ⚠️] Error tracking dependent inserts: {e}")

@event.listens_for(Session, "after_commit")
def confirm_commit(session):
    """Optional: print commit summary."""
    if any([session.new, session.dirty, session.deleted]):
        print(f"[commit ✅] {len(session.new)} inserted, {len(session.dirty)} updated, {len(session.deleted)} deleted.")
