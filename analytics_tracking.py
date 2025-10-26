# analytics_tracker.py
import json
import os
import sys
from datetime import datetime
from logging import exception
from pathlib import Path
import structlog
import requests

basedir = Path(__file__).parent.resolve()


def _desktop_data_dir(app_name: str) -> Path:
    if os.name == "nt":
        return Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / app_name
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    else:
        return Path.home() / ".local" / "share" / app_name


def get_log_file_name_analytics(current_page: str):
    timestamp = datetime.now().strftime("%H%M%S")
    filename = f"{datetime.today().strftime('%Y%m%d')}_{timestamp}_{current_page}.json"
    today = datetime.now().strftime("%d-%m-%Y")

    APP_NAME = "SLO BILL"
    is_desktop = os.getenv("BG_DESKTOP") == "1"

    if is_desktop:
        data_dir = _desktop_data_dir(APP_NAME)
        data_dir.mkdir(parents=True, exist_ok=True)
        log_file = data_dir / "logs" / today / "analytics" / filename
    else:
        log_file = basedir / "logs" / today / "analytics" / filename
        log_file.parent.mkdir(parents=True, exist_ok=True)

    return log_file


def _write_new_analytics_log(log_data):
    filename = get_log_file_name_analytics(current_page=log_data['current_page'])

    with open(filename, "w") as f:
        f.write("[\n")
        json.dump(log_data, f, indent=2)
        f.write("\n]")


def log_user_event(data):
    """Append analytics event data to daily analytics log file."""
    APP_NAME = "SLO BILL"
    is_desktop = os.getenv("BG_DESKTOP") == "1"
    today_str = datetime.now().strftime("%Y_%m_%d")
    date_dir_str = datetime.now().strftime("%d-%m-%Y")

    if is_desktop:
        data_dir = _desktop_data_dir(APP_NAME)
        log_dir = data_dir / "logs" / date_dir_str / "analytics"
    else:
        log_dir = basedir / "logs" / date_dir_str / "analytics"

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"analytics_{today_str}.json"

    # Ensure all required fields exist with default None if missing
    entry = {
        "timestamp": data.get("timestamp") or datetime.utcnow().isoformat(),
        "current_page": data.get("current_page"),
        "activity": data.get("activity"),
        "click": data.get("click"),
        "time_spent": data.get("time_spent"),
        "previous_page": data.get("previous_page"),
        "user": data.get("user"),
    }

    try:
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                if not isinstance(existing_data, list):
                    existing_data = []
        else:
            existing_data = []

        existing_data.append(entry)

        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2)

    except Exception as e:
        print(f"Error logging user event: {e}")
