# analytics_tracker.py
import json
import os
import sys
from datetime import datetime
from logging import exception
from pathlib import Path
import structlog

LOG_FILE = "user_activity_log.json"
basedir = Path(__file__).parent.resolve()

def _desktop_data_dir(app_name: str) -> Path:
    if os.name == "nt":
        return Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / app_name
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    else:
        return Path.home() / ".local" / "share" / app_name

def get_log_file_name(action: str, transaction_id):
    timestamp = datetime.now().strftime("%H%M%S")
    filename = f"{datetime.today().strftime('%Y%m%d')}_{timestamp}_{action}_{transaction_id}.json"
    today = datetime.now().strftime("%d-%m-%Y")

    APP_NAME = "SLO BILL"
    is_desktop = os.getenv("BG_DESKTOP") == "1"

    if is_desktop:
        data_dir = _desktop_data_dir(APP_NAME)
        data_dir.mkdir(parents=True, exist_ok=True)
        log_file = data_dir / "logs" / today / "activity" / filename
    else:
        log_file = basedir / "logs" / today / "activity" / filename
        log_file.parent.mkdir(parents=True, exist_ok=True)

    return log_file

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


def _write_new_log(log_data):
    filename = get_log_file_name(log_data['activity'], log_data["txn_id"])

    with open(filename, "w") as f:
        f.write("[\n")
        json.dump(log_data, f, indent=2)
        f.write("\n]")

def _write_new_analytics_log(log_data):
    filename = get_log_file_name_analytics(current_page=log_data['current_page'])

    with open(filename, "w") as f:
        f.write("[\n")
        json.dump(log_data, f, indent=2)
        f.write("\n]")



def user_activity_log(current_page, activity, txn_id, details = None, user = 'default'):
    """Takes in details and sets up logs in a json file"""
    timestamp = datetime.utcnow().isoformat()

    log_data = {'current_page': current_page,
                'activity': activity,
                'timestamp': timestamp,
                'user': user,
                'details': details,
                'txn_id': txn_id}

    try:
        _write_new_log(log_data)
    except Exception as e:
        print(e)

def user_analytics_logs(current_page, activity, click = None, time_spent = None, previous_page = None, user = 'default'):
    """Takes in details and sets up logs in a json file"""
    timestamp = datetime.utcnow().isoformat()

    log_data = {
        'current_page': current_page,
        'activity': activity,
        'time_spent': time_spent,
        'previous_page': previous_page,
        'user': user,
        'click': click,
    }

    try:
        _write_new_analytics_log(log_data)
    except Exception as e:
        print(e)

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