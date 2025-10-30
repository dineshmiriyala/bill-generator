import atexit
import csv
import io
import json
import os
import shutil
import sys
import sqlite3
import uuid
from collections import defaultdict
from copy import deepcopy
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlparse

import requests
import stat
from dateutil import tz, parser
from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    render_template_string,
    request,
    send_file,
    session,
    url_for,
)
from flask_migrate import Migrate
from sqlalchemy import func, inspect, or_
from sqlalchemy.orm import joinedload

from analytics import (
    get_customer_retention,
    get_day_wise_billing,
    get_sales_trends,
    get_top_customers,
)
from analytics_tracking import log_user_event
from api import api_bp
from db import db_events  # noqa: F401
from db.models import db, customer, invoice, invoiceItem, item, layoutConfig
from migration import migrate_db
from supabase_upload import SupabaseUploadError, upload_full_database, upload_to_supabase

APP_NAME = "SLO BILL"
BG_DESKTOP_ENV = "BG_DESKTOP"
DEFAULT_SECRET_KEY = "super-secret"
DATABASE_FILENAME = "app.db"
INFO_FILENAME = "info.json"
APP_VERSION = "3.1.2"
DEFAULT_TIMEZONE = "Asia/Kolkata"
REQUIRED_DB_TABLES = {"customer", "invoice", "invoice_item", "item"}
BACKUP_DIRNAME = "backups"
BACKUP_RETENTION = 10
BACKUP_MAX_AGE_DAYS = 7
ISO_8601_UTC = "%Y-%m-%dT%H:%M:%SZ"
HUMAN_DATE_FMT = "%d %B %Y"


def _default_info_sections(reference_dt: Optional[datetime] = None) -> dict:
    """Return a fresh copy of default info.json sections."""
    reference_dt = reference_dt or datetime.now(timezone.utc)
    iso_now = reference_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    current_year = str(reference_dt.year)

    return {
        "business": {
            "name": "",
            "owner": "",
            "address": "",
            "email": "",
            "phone": "",
            "gstin": "",
            "upi_id": "",
            "upi_name": "",
            "businessType": "",
            "pan": "",
            "estd": current_year,
            "logo_path": "static/img/brand-wordmark.svg",
        },
        "bank": {
            "account_name": "",
            "bank_name": "",
            "branch": "",
            "account_number": "",
            "ifsc": "",
            "bhim": "",
        },
        "appearance": {
            "currency_symbol": "\\u20b9",
            "date_format": "%d %B %Y",
            "font_family": "Inter, Helvetica, Arial, sans-serif",
            "theme_color": "#0056b3",
        },
        "payment": {
            "methods": ["Bank Transfer", "UPI"],
            "upi_qr_enabled": False,
            "qr_label": "Scan to Pay",
            "terms": [
                "Payment due within 7 days of invoice date.",
                "Late payments may incur a 2% interest per month.",
                "This is a computer-generated document, no signature required.",
            ],
        },
        "statement": {
            "header_title": "Statement Summary",
            "disclaimer": "This is a system-generated statement. No signature required.",
        },
        "account_defaults": {
            "start_date": iso_now,
            "timezone": DEFAULT_TIMEZONE,
        },
        "meta": {
            "version": APP_VERSION,
            "created_on": iso_now,
        },
        "upi_info": {
            "upi_id": "",
            "currency": "INR",
            "upi_name": "",
        },
        "services": [
            "Printing",
            "Design",
            "Branding Collateral",
        ],
        "bill_config": {
            "heading": "Tax Invoice",
            "footer": "Composition Taxable Person. Not eligible to collect Tax on supplies.",
            "payment-footer": "Computer generated receipt - Signature not required",
        },
        "file_location": "",
        "supabase": {
            "url": "",
            "key": "",
            "last_uploaded": "",
            "last_incremental_uploaded": "",
        },
    }


def _merge_missing(target: dict, defaults: dict) -> bool:
    """Merge missing keys from defaults into target. Returns True if mutated."""
    changed = False
    for key, default_value in defaults.items():
        if key not in target:
            target[key] = deepcopy(default_value)
            changed = True
        else:
            current_value = target[key]
            if isinstance(default_value, dict) and isinstance(current_value, dict):
                if _merge_missing(current_value, default_value):
                    changed = True
    return changed


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize datetimes to UTC with timezone info."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso_utc(dt: datetime) -> str:
    return _ensure_utc(dt).strftime(ISO_8601_UTC)


def _format_human_date(dt: datetime) -> str:
    return _ensure_utc(dt).strftime(HUMAN_DATE_FMT)


def _get_earliest_invoice_created_at() -> Optional[datetime]:
    """Fetch the earliest invoice.createdAt value from the DB."""
    try:
        with app.app_context():
            earliest = (
                db.session.query(func.min(invoice.createdAt))
                .filter(invoice.isDeleted == False)  # noqa: E712
                .scalar()
            )
    except Exception as exc:
        print(f"[warn] Failed to determine earliest invoice date: {exc}")
        return None

    if not earliest:
        return None

    if isinstance(earliest, str):
        try:
            earliest = datetime.strptime(earliest, ISO_8601_UTC)
        except Exception:
            return None

    return _ensure_utc(earliest)


def _determine_data_start(now: datetime) -> datetime:
    """Return the correct account start date, preferring the first invoice date."""
    earliest = _get_earliest_invoice_created_at()
    if not earliest:
        return now

    earliest_utc = _ensure_utc(earliest)
    # Guard against corrupted future dates
    if earliest_utc > now:
        return now
    return earliest_utc


def _ensure_file_writable(path: Path) -> None:
    """Best-effort to guarantee the SQLite file is writable (fixes Windows bundle perms)."""
    try:
        if not path.exists():
            return
        if os.name == "nt":
            path.chmod(stat.S_IWRITE | stat.S_IREAD)
        else:
            path.chmod(0o600)
    except Exception as exc:
        print(f"[warn] Could not adjust permissions for {path}: {exc}")


def _desktop_data_dir(app_name: str) -> Path:
    if os.name == "nt":
        return Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / app_name
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    return Path.home() / ".local" / "share" / app_name


BASE_DIR = Path(__file__).resolve().parent
IS_DESKTOP = os.getenv(BG_DESKTOP_ENV) == "1"
DATA_DIR = _desktop_data_dir(APP_NAME) if IS_DESKTOP else BASE_DIR / "db"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / DATABASE_FILENAME
SEED_DB_PATH = BASE_DIR / "db" / DATABASE_FILENAME
INFO_PATH = DATA_DIR / INFO_FILENAME


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH.as_posix()}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.register_blueprint(api_bp)

migrate_db(DB_PATH.as_posix())

# Attach to this Flask app
db.init_app(app)
migrate = Migrate(app, db)


def _format_customer_id(n: int) -> str:
    return f"ID-{n:06d}"


def rounding_to_nearest_zero(amount):
    """Rounding number to nearest zero"""
    try:
        d = Decimal(str(amount))
    except Exception:
        d = Decimal('0')
    tens = (d / Decimal('10')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return float(tens * Decimal('10'))


def _ensure_db_initialized():
    """
    Ensure database schema exists.
    - If DB file missing: create schema (or copy seed if present + desktop).
    - If DB file exists but has no tables: create schema.
    """
    with app.app_context():
        # create file if missing (and optionally copy seed on desktop)
        if not DB_PATH.exists():
            try:
                if SEED_DB_PATH.exists() and IS_DESKTOP:
                    shutil.copy2(SEED_DB_PATH, DB_PATH)
                    print("[info] Copied seed DB to desktop data dir.")
                else:
                    # touch file so engine can open it cleanly
                    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                    DB_PATH.touch(exist_ok=True)
                    print("[info] Created empty DB file.")
            except Exception as e:
                print(f"[warn] could not prepare DB file: {e}")
        # Always ensure the DB file is writable (pyinstaller seed copies can be read-only on Windows)
        _ensure_file_writable(DB_PATH)
        if DB_PATH.exists() and os.name == "nt":
            try:
                test_conn = sqlite3.connect(DB_PATH.as_posix())
                test_conn.execute("PRAGMA user_version;")
                test_conn.close()
            except sqlite3.OperationalError as exc:
                if "readonly" in str(exc).lower():
                    print("[warn] Detected read-only SQLite database; retrying permission reset.")
                    _ensure_file_writable(DB_PATH)
                else:
                    print(f"[warn] SQLite connection check failed: {exc}")

        # check whether tables exist
        insp = inspect(db.engine)
        tables = set(insp.get_table_names())

        if not REQUIRED_DB_TABLES.issubset(tables):
            print("[info] Creating/migrating schema via create_all()…")
            db.create_all()


def get_info_json_path():
    """Return correct info.json path"""
    return INFO_PATH


def ensure_info_json():
    """ensure db info.json exists or else creates it"""
    info_path = get_info_json_path()
    if not info_path.parent.exists():
        info_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    determined_start = _determine_data_start(now)
    start_iso = _format_iso_utc(determined_start)
    start_dt = _ensure_utc(datetime.strptime(start_iso, ISO_8601_UTC))
    created_display = _format_human_date(start_dt)

    default_sections = _default_info_sections(start_dt)
    default_sections["account_defaults"]["start_date"] = start_iso
    default_sections["meta"]["created_on"] = start_iso

    default_payload = {
        "created_on": created_display,
        "app_name": APP_NAME,
        "version": APP_VERSION,
        "last_updated": now.strftime(HUMAN_DATE_FMT),
        "onboarding_complete": False,
        "data": default_sections,
    }

    if not info_path.exists():
        try:
            with open(info_path, "w", encoding='utf-8') as f:
                json.dump(default_payload, f, indent=2, ensure_ascii=False)
            print("[info] Created info.json with default structure.")
        except Exception as e:
            print(f"[warn] could not create db info.json: {e}")
        return info_path

    try:
        with open(info_path, "r", encoding='utf-8') as f:
            info_data = json.load(f)
    except Exception as exc:
        print(f"[warn] Failed to read info.json ({exc}); rewriting with defaults.")
        try:
            with open(info_path, "w", encoding='utf-8') as f:
                json.dump(default_payload, f, indent=2, ensure_ascii=False)
        except Exception as write_err:
            print(f"[warn] could not rewrite db info.json: {write_err}")
        return info_path

    changed = False
    for key in ("created_on", "app_name", "version", "last_updated"):
        if key not in info_data:
            info_data[key] = default_payload[key]
            changed = True

    if "onboarding_complete" not in info_data:
        info_data["onboarding_complete"] = False
        changed = True

    if not isinstance(info_data.get("data"), dict):
        info_data["data"] = deepcopy(default_sections)
        changed = True
    else:
        if _merge_missing(info_data["data"], default_sections):
            changed = True

    data_section = info_data["data"]

    account_defaults = data_section.setdefault("account_defaults", {})
    existing_start = account_defaults.get("start_date")
    if existing_start:
        try:
            existing_start_dt = _ensure_utc(datetime.strptime(existing_start, ISO_8601_UTC))
        except Exception:
            account_defaults["start_date"] = start_iso
            changed = True
        else:
            if existing_start_dt > start_dt:
                account_defaults["start_date"] = start_iso
                changed = True
    else:
        account_defaults["start_date"] = start_iso
        changed = True

    meta_section = data_section.setdefault("meta", {})
    meta_created = meta_section.get("created_on")
    if meta_created:
        try:
            meta_dt = _ensure_utc(datetime.strptime(meta_created, ISO_8601_UTC))
        except Exception:
            meta_section["created_on"] = start_iso
            changed = True
        else:
            if meta_dt != start_dt:
                meta_section["created_on"] = start_iso
                changed = True
    else:
        meta_section["created_on"] = start_iso
        changed = True

    created_on_value = info_data.get("created_on")
    if created_on_value:
        try:
            created_on_dt = datetime.strptime(created_on_value, HUMAN_DATE_FMT).replace(tzinfo=timezone.utc)
        except Exception:
            info_data["created_on"] = created_display
            changed = True
        else:
            if created_on_dt.date() != start_dt.date():
                info_data["created_on"] = created_display
                changed = True
    else:
        info_data["created_on"] = created_display
        changed = True

    if changed:
        try:
            with open(info_path, "w", encoding='utf-8') as f:
                json.dump(info_data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[warn] Failed to update info.json defaults: {exc}")

    return info_path


def loading_info():
    info_path = ensure_info_json()

    with open(info_path, 'r', encoding='utf-8') as f:
        json_loaded = json.load(f)
        return json_loaded


def refresh_info_json():
    """Reload the info.json without restarting the app"""
    global APP_INFO, ONBOARDING_COMPLETE
    try:
        full_payload = loading_info()
        new_info = full_payload.get('data', {})
        if not isinstance(new_info, dict):
            new_info = {}
        APP_INFO.clear()
        APP_INFO.update(new_info)
        ONBOARDING_COMPLETE = bool(full_payload.get('onboarding_complete', False))
    except Exception as e:
        print(f"[warn] Failed to load/refresh app_info: {e}")


_initial_info_payload = loading_info()
APP_INFO = _initial_info_payload.get('data', {})
if not isinstance(APP_INFO, dict):
    APP_INFO = {}
ONBOARDING_COMPLETE = bool(_initial_info_payload.get('onboarding_complete', False))


ONBOARDING_EXEMPT_ENDPOINTS = {
    'static',
    'onboarding',
    'onboarding_submit',
    'config_refresh',
}


def _is_onboarding_complete() -> bool:
    return bool(ONBOARDING_COMPLETE)


def _clean_analytics_payload(data: dict) -> dict:
    """Remove empty values and normalise strings from analytics payloads."""
    if not isinstance(data, dict):
        return {}

    cleaned = {}
    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip()
        if value in (None, ""):
            continue
        cleaned[key] = value
    return cleaned


@app.before_request
def _enforce_onboarding_flow():
    if _is_onboarding_complete():
        return

    endpoint = request.endpoint or ''
    if endpoint in ONBOARDING_EXEMPT_ENDPOINTS:
        return
    if endpoint.startswith('api_bp.'):
        return

    return redirect(url_for('onboarding'))


@app.route('/onboarding', methods=['GET'])
def onboarding():
    if _is_onboarding_complete():
        return redirect(url_for('home'))

    seed_info = loading_info().get('data', {})
    business_defaults = seed_info.get('business', {}) if isinstance(seed_info, dict) else {}
    bank_defaults = seed_info.get('bank', {}) if isinstance(seed_info, dict) else {}
    return render_template(
        'onboarding.html',
        business=business_defaults,
        bank=bank_defaults,
    )


def _normalize_account_number(value: str) -> str:
    return ''.join(ch for ch in value if ch.isalnum())


@app.route('/onboarding/submit', methods=['POST'])
def onboarding_submit():
    if _is_onboarding_complete():
        flash('Onboarding already completed.', 'info')
        return redirect(url_for('home'))

    form = request.form

    def _clean(key: str) -> str:
        return (form.get(key) or '').strip()

    business_name = _clean('business_name')
    owner_name = _clean('owner_name')
    phone = _clean('phone')
    email = _clean('email')
    address = _clean('address')
    upi_id = _clean('upi_id')
    gstin = _clean('gstin').upper()
    business_type = _clean('business_type')
    pan = _clean('pan').upper()

    bank_account_number = _clean('bank_account_number')
    confirm_bank_account_number = _clean('confirm_bank_account_number')
    ifsc_code = _clean('ifsc_code').upper()
    account_holder_name = _clean('account_holder_name') or business_name
    branch_name = _clean('branch_name')
    bank_name = _clean('bank_name')

    skip_bank = form.get('skip_bank', 'false').lower() == 'true'

    errors: List[str] = []
    if not business_name:
        errors.append('Business name is required.')
    if not owner_name:
        errors.append('Owner name is required.')
    if not phone:
        errors.append('Phone number is required.')

    normalized_account = _normalize_account_number(bank_account_number)
    normalized_confirm = _normalize_account_number(confirm_bank_account_number)

    if not skip_bank:
        if not normalized_account:
            errors.append('Bank account number is required or choose skip.')
        elif normalized_account != normalized_confirm:
            errors.append('Bank account numbers do not match.')

    if errors:
        for err in errors:
            flash(err, 'danger')
        return redirect(url_for('onboarding'))

    now = datetime.now(timezone.utc)
    info_payload = loading_info()
    data_section = _default_info_sections(now)

    # Business details
    data_section['business'].update({
        'name': business_name,
        'owner': owner_name,
        'address': address,
        'email': email,
        'phone': phone,
        'gstin': gstin,
        'upi_id': upi_id,
        'upi_name': owner_name or business_name,
        'businessType': business_type,
        'pan': pan,
    })

    # Bank details (optional)
    if not skip_bank:
        data_section['bank'].update({
            'account_name': account_holder_name,
            'bank_name': bank_name,
            'branch': branch_name,
            'account_number': normalized_account,
            'ifsc': ifsc_code,
            'bhim': phone,
        })

    # Payment / UPI info
    data_section['upi_info'].update({
        'upi_id': upi_id,
        'upi_name': owner_name or business_name,
    })
    payment_methods = [m for m in data_section['payment'].get('methods', [])]
    if upi_id:
        if 'UPI' not in (method.upper() for method in payment_methods):
            payment_methods.insert(0, 'UPI')
        data_section['payment']['upi_qr_enabled'] = True
    else:
        payment_methods = [m for m in payment_methods if m.upper() != 'UPI'] or ['Bank Transfer']
        data_section['payment']['upi_qr_enabled'] = False
    data_section['payment']['methods'] = payment_methods

    # Account defaults / meta
    data_section['account_defaults']['start_date'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    data_section['meta']['version'] = APP_VERSION
    data_section['meta']['created_on'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    info_payload['data'] = data_section
    info_payload['onboarding_complete'] = True
    info_payload['last_updated'] = now.strftime('%d %B %Y')
    info_payload.setdefault('created_on', now.strftime('%d %B %Y'))
    info_payload.setdefault('app_name', APP_NAME)
    info_payload['version'] = APP_VERSION

    info_path = get_info_json_path()
    try:
        with open(info_path, 'w', encoding='utf-8') as f:
            json.dump(info_payload, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        flash(f'Failed to save onboarding details: {exc}', 'danger')
        return redirect(url_for('onboarding'))

    refresh_info_json()
    flash('Setup complete! You can start generating invoices.', 'success')
    return redirect(url_for('home'))


def get_default_statement_start():
    """Return default statement start date from info.json"""
    tzinfo = tz.gettz(APP_INFO['account_defaults']['timezone'])
    return datetime.strptime(
        APP_INFO['account_defaults']['start_date'], '%Y-%m-%dT%H:%M:%SZ'
    ).replace(tzinfo=tzinfo)


# Call this AFTER importing models, so metadata is populated
with app.app_context():
    _ensure_db_initialized()


# --- routes continue below as usual ---

# Helpers for statement engine
def _parse_date(date_str):
    """Parse 'YYYY-MM-DD' into date or return None."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except Exception:
        return None


@app.route('/recover')
def recover_page():
    deleted_customers = customer.query.filter_by(isDeleted=True).all()
    deleted_invoices = invoice.query.filter_by(isDeleted=True).all()
    return render_template(
        'recover.html',
        deleted_customers=deleted_customers,
        deleted_invoices=deleted_invoices
    )


@app.route('/recover_customer/<int:id>')
def recover_customer(id):
    cust = customer.query.get_or_404(id)
    cust.isDeleted = False
    db.session.commit()
    flash('Customer recovered successfully.', 'success')
    return redirect(url_for('recover_page'))


@app.route('/more')
def more():
    supabase_meta = APP_INFO.get('supabase', {})
    last_sync_raw = supabase_meta.get('last_incremental_uploaded') or supabase_meta.get('last_uploaded')
    last_sync_display = _format_sync_timestamp(last_sync_raw)

    latest_backup = _latest_backup_path()
    if latest_backup:
        backup_iso = datetime.fromtimestamp(latest_backup.stat().st_mtime, tz=timezone.utc).isoformat()
        last_backup_display = _format_sync_timestamp(backup_iso)
        last_backup_name = latest_backup.name
    else:
        last_backup_display = "Never"
        last_backup_name = None

    return render_template(
        'more.html',
        has_backup_location=bool((APP_INFO.get('file_location') or '').strip()),
        last_sync_display=last_sync_display,
        last_backup_display=last_backup_display,
        last_backup_name=last_backup_name,
    )


@app.route('/analytics_event', methods=['GET', 'POST'])
def analytics_event():
    try:
        data = request.get_json(silent=True)

        if not data and request.form:
            data = request.form.to_dict(flat=True)

        if not data and request.data:
            try:
                data = json.loads(request.data.decode('utf-8') or '{}')
            except json.JSONDecodeError:
                data = {}

        normalized = _clean_analytics_payload(data or {})

        if not normalized:
            # Gracefully acknowledge empty analytics pings without treating them as errors
            return jsonify({"status": "ignored", "message": "No analytics payload supplied."}), 204

        # Call the logger in analytics_tracking.py
        log_user_event(normalized)

        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"[warn] Analytics log failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/analytics')
def analytics():
    # Get sales trends for day, month, year, and weekday
    day_labels, day_totals = get_sales_trends("day")
    month_labels, month_totals = get_sales_trends("month")
    year_labels, year_totals = get_sales_trends("year")
    # Fetch weekday-level sales trends
    weekday_labels, weekday_totals = get_sales_trends("weekday")
    customer_names, revenues = get_top_customers()
    one_time, repeat = get_customer_retention()
    daywise_labels, daywise_counts, daywise_totals = get_day_wise_billing()

    return render_template(
        'analytics.html',
        day_labels=day_labels,
        day_totals=day_totals,
        month_labels=month_labels,
        month_totals=month_totals,
        year_labels=year_labels,
        year_totals=year_totals,
        weekday_labels=weekday_labels,
        weekday_totals=weekday_totals,
        customer_names=customer_names,
        revenues=revenues,
        one_time=one_time,
        repeat=repeat,
        daywise_labels=daywise_labels,
        daywise_counts=daywise_counts,
        daywise_totals=daywise_totals,
    )


@app.route('/about_user', methods=['GET', 'POST'])
def about_user():
    customer_id = request.args.get('customer_id')
    cust = customer.query.filter_by(id=customer_id, isDeleted=False).first_or_404()
    data = {
        'id': cust.id,
        'name': cust.name,
        'email': cust.email,
        'company': cust.company,
        'phone': cust.phone,
        'gst': cust.gst,
        'address': cust.address,
        'businessType': cust.businessType
    }
    return render_template(
        'about_user.html',
        data=data,
        app_info=APP_INFO

    )


@app.route('/edit_user/<int:customer_id>', methods=['GET', 'POST'])
def edit_user(customer_id):
    cust = customer.query.filter_by(id=customer_id, isDeleted=False).first_or_404()

    if request.method == 'GET':
        return render_template('edit_user.html', customer=cust)

    # POST logic: update values
    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    address = request.form.get('address', '').strip()
    gst = request.form.get('gst', '').strip()
    email = request.form.get('email', '').strip()
    businessType = request.form.get('businessType', '').strip()
    company = request.form.get('company', '').strip()

    if not name or not phone:
        flash('Name and Phone are required fields.', 'warning')
        return redirect(request.referrer or url_for('about_user', customer_id=customer_id))

    cust.name = name
    cust.phone = phone
    cust.address = address
    cust.gst = gst
    cust.email = email
    cust.businessType = businessType
    cust.company = company

    try:
        db.session.commit()
        flash('Customer updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating customer: {e}', 'danger')

    next_url = request.form.get('next') or url_for('about_user', customer_id=customer_id)
    return redirect(next_url)


@app.route('/recover_invoice/<int:id>')
def recover_invoice(id):
    inv = invoice.query.get_or_404(id)
    inv.isDeleted = False
    db.session.commit()
    flash('Invoice recovered successfully.', 'success')
    return redirect(url_for('recover_page'))


# Custom Jinja filter to format dates as DD Month YYYY (e.g., '14 October 2025')
@app.template_filter('datetimeformat')
def datetimeformat(value, format='%d %B %Y'):
    """Safely format a date string or datetime into a readable form (e.g., '14 October 2025')."""
    if not value:
        return ''
    try:
        if isinstance(value, str):
            # Try parsing both full and simple date formats
            for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S'):
                try:
                    value = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    continue
        return value.strftime(format)
    except Exception:
        return str(value)


@app.route('/_flash_test')
def _flash_test():
    flash('Flash works!', 'success')
    return redirect(url_for('view_customers'))


# Home Route
@app.route('/')
def home():
    session['persistent_notice'] = None
    supabase_meta = APP_INFO.get('supabase', {})
    last_incremental = supabase_meta.get('last_incremental_uploaded')
    last_full = supabase_meta.get('last_uploaded')
    display_last = _format_sync_timestamp(last_incremental or last_full)
    return render_template('home.html', last_uploaded=display_last)


@app.route('/config', methods=['GET', 'POST'])
def config():
    info_path = get_info_json_path()

    # --- Load existing info.json ---
    with open(info_path, 'r', encoding='utf-8') as f:
        info_data = json.load(f)

    app_info = info_data.get("data", {})
    if not isinstance(app_info, dict):
        app_info = {}
    if 'file_location' not in app_info:
        app_info['file_location'] = ''

    # --- Handle POST (Save Changes) ---
    if request.method == 'POST':
        section = request.form.get('section')
        if not section:
            flash('No section specified for update.', 'warning')
            return redirect(url_for('config'))

        # Get editable section data
        updates = {}
        for key, val in request.form.items():
            if key not in ('section',):
                updates[key] = val.strip()

        # Apply updates to correct section
        if section == 'file_location':
            new_path = updates.get('file_location') or updates.get('value') or ''
            app_info['file_location'] = new_path.strip()
        elif section in app_info:
            if isinstance(app_info[section], dict):
                app_info[section].update(updates)
            elif isinstance(app_info[section], list):
                # handle lists (e.g., services textarea)
                lines = updates.get('services', '').splitlines()
                app_info[section] = [ln.strip() for ln in lines if ln.strip()]
            else:
                # simple scalar fields
                value = updates.get(section) or updates.get('value')
                app_info[section] = value.strip() if isinstance(value, str) else updates
        else:
            app_info[section] = updates

        # Update timestamp + save to file
        info_data['data'] = app_info
        info_data['last_updated'] = datetime.now(timezone.utc).strftime("%d %B %Y")

        try:
            with open(info_path, 'w', encoding='utf-8') as f:
                json.dump(info_data, f, indent=2, ensure_ascii=False)
            section_label = section.replace('_', ' ').title()
            flash(f"{section_label} updated successfully!", "success")
            refresh_info_json()
        except Exception as e:
            flash(f"Error saving changes: {e}", "danger")

        # Reload updated version
        return redirect(url_for('config'))

    # --- Default (GET) view ---
    return render_template('config_editor.html', app_info=app_info,
                           last_updated=info_data['last_updated'],
                           created_on=info_data['created_on'])


@app.route('/config/refresh', methods=['POST'])
def config_refresh():
    try:
        refresh_info_json()
        flash('Account settings reloaded from info.json.', 'success')
    except Exception as exc:
        flash(f'Unable to refresh settings: {exc}', 'danger')
    return redirect(url_for('config'))


# customers page (temperory placeholder)
@app.route('/create_customers', methods=['GET', 'POST'])
def add_customers():
    if request.method == 'POST':
        use_auto = bool(request.form.get('use_auto_id'))
        phone = (request.form.get('phone') or '').strip()
        name = (request.form.get('name') or '').strip()
        company = (request.form.get('company') or '').strip()
        email = (request.form.get('email') or '').strip()
        gst = (request.form.get('gst') or '').strip()
        address = (request.form.get('address') or '').strip()
        businessType = (request.form.get('businessType') or '').strip()

        # --- Basic validation ---
        if not name or (not use_auto and not phone):
            return render_template(
                'add_customer.html',
                success=False,
                duplicate=False,
                error='Name is required. Phone is required unless you use computer-generated ID.',
                # sticky values
                name=name, company=company, phone=phone, email=email,
                gst=gst, address=address, businessType=businessType,
                use_auto_id=use_auto
            )

        # --- Duplicate checks (exclude soft-deleted if you have that flag) ---
        not_deleted = getattr(customer, 'isDeleted', False) == False

        # 1) Phone duplicate (only when not using auto-id)
        if not use_auto and phone:
            existing_phone = (customer.query
                              .filter(func.lower(customer.phone) == phone.lower(), not_deleted)
                              .first())
            if existing_phone:
                return render_template(
                    'add_customer.html',
                    duplicate=True,
                    error='A customer with this phone already exists.',
                    name=name, company=company, phone=phone, email=email,
                    gst=gst, address=address, businessType=businessType,
                    use_auto_id=use_auto
                )

        # 2) Company+Name duplicate (case-insensitive)
        if company and name:
            existing_pair = (customer.query
                             .filter(func.lower(customer.company) == company.lower(),
                                     func.lower(customer.name) == name.lower(),
                                     not_deleted)
                             .first())
            if existing_pair:
                return render_template(
                    'add_customer.html',
                    duplicate=True,
                    error='A customer with the same Company + Name already exists.',
                    name=name, company=company, phone=phone, email=email,
                    gst=gst, address=address, businessType=businessType,
                    use_auto_id=use_auto
                )

        # --- Create customer ---
        if not use_auto and phone:
            # Real phone path
            c = customer(
                name=name, company=company, phone=phone, email=email,
                gst=gst, address=address, businessType=businessType
            )
            db.session.add(c)
            db.session.commit()
            # add alert
            flash('New Customer Created successfully.', 'success')
            return redirect(url_for('about_user', customer_id=c.id))

        # Auto-ID path (no real phone or toggle checked)
        temp_phone = f"ID-TEMP-{uuid.uuid4().hex[:8]}"
        c = customer(
            name=name, company=company, phone=temp_phone, email=email,
            gst=gst, address=address, businessType=businessType
        )

        db.session.add(c)
        db.session.flush()  # get c.id
        c.phone = _format_customer_id(c.id)  # e.g., ID-000123
        db.session.commit()
        # add alert
        flash('New Customer Created successfully.', 'success')

        return redirect(url_for('about_user', customer_id=c.id))

    # GET -> render blank form
    return render_template('add_customer.html')


@app.route('/delete_customer/<int:cid>', methods=['GET', 'POST'])
def delete_customer(cid):
    # Load customer
    c = db.session.get(customer, cid)
    if not c:
        flash("Customer not found", 'warning')
        return redirect(url_for('view_customers'))

    # If already deleted, bail gracefully
    if hasattr(c, 'isDeleted') and c.isDeleted:
        flash('Customer already deleted.', 'info')
        return redirect(url_for('view_customers'))

    # Live invoices (exclude soft-deleted)
    inv_q = invoice.query.filter(
        invoice.customerId == cid,
        getattr(invoice, 'isDeleted', False) == False
    )
    inv_count = inv_q.count()
    total_billed = db.session.query(
        func.coalesce(func.sum(invoice.totalAmount), 0.0)
    ).filter(
        invoice.customerId == cid,
        getattr(invoice, 'isDeleted', False) == False
    ).scalar() or 0.0

    # If POST with confirm flag -> cascade soft-delete customer + invoices
    if request.method == 'POST' and request.form.get('confirm') == '1':
        if hasattr(c, 'isDeleted'):
            c.isDeleted = True
        # Soft delete all invoices for this customer
        invs = invoice.query.filter_by(customerId=cid).all()
        for inv in invs:
            if hasattr(inv, 'isDeleted'):
                inv.isDeleted = True
                inv.deletedAt = datetime.now(timezone.utc)
        db.session.commit()
        # add alert,
        flash('Customer and related invoices deleted successfully.', 'danger')
        return redirect(url_for('view_customers'))

    # GET: If invoices exist but not confirmed yet -> show confirm page
    if request.method == 'GET' and inv_count > 0:
        return render_template(
            'confirm_delete_customer.html',
            customer=c,
            inv_count=inv_count,
            total_billed=total_billed
        )

    # No invoices -> delete immediately (GET or POST)
    if hasattr(c, 'isDeleted'):
        c.isDeleted = True
        db.session.commit()
        flash('Customer deleted.', 'danger')
    else:
        flash('Delete not available in this build.', 'warning')

    return redirect(url_for('view_customers'))


@app.route('/add_inventory', methods=['GET', 'POST'])
def add_inventory():
    # this function will be used to create a new inventory item.
    if request.method == 'POST':
        # Read and normalize inputs
        name = (request.form.get('name') or '').strip()
        unit_price_raw = (request.form.get('unitPrice') or '').strip()
        qty_raw = (request.form.get('quantity') or '').strip()
        tax_raw = (request.form.get('taxPercentage') or '').strip()

        # Basic validation
        if not name:
            return render_template('add_inventory.html', success=False, error='Item name is required.')

        try:
            unit_price = float(unit_price_raw or 0)
        except ValueError:
            return render_template('add_inventory.html', success=False, error='Unit price must be a number.')

        try:
            qty = int(qty_raw or 10000)
        except ValueError:
            return render_template('add_inventory.html', success=False, error='Quantity must be an integer.')

        try:
            tax_pct = float(tax_raw or 0)
        except ValueError:
            return render_template('add_inventory.html', success=False, error='Tax % must be a number.')

        # Duplicate check by name (case-insensitive)
        existing = item.query.filter(func.lower(item.name) == name.lower()).first()
        if existing:
            return render_template('add_inventory.html', duplicate=True)

        # Create item; SKU auto-assigned by model's before_insert listener
        new_item = item(
            name=name,
            unitPrice=unit_price,
            quantity=qty,
            taxPercentage=tax_pct
        )
        db.session.add(new_item)
        db.session.commit()
        # add alert
        flash('Item added successfully.', 'success')
        return render_template('add_inventory.html', success=True)

    return render_template('add_inventory.html')


@app.route('/select_customer', methods=['GET', 'POST'])
def select_customer():
    if request.method == 'POST':
        # User clicked Select on a customer row; the form sends phone
        phone = request.form.get('customer')
        sel = (customer.query
               .filter(customer.isDeleted == False, customer.phone == phone)
               .first_or_404())
        return render_template('create_bill.html', customer=sel, inventory=item.query.all())

    # GET: either search or show recent
    q = (request.args.get('q') or '').strip()
    base = customer.query.filter(customer.isDeleted == False)
    if q:
        like = f"%{q}%"
        customers = (base.filter((customer.phone.ilike(like)) |
                                 (customer.name.ilike(like)) |
                                 (customer.company.ilike(like)))
                     .order_by(customer.id.desc())
                     .limit(100)
                     .all())
    else:
        customers = (base.order_by(customer.id.desc())
                     .limit(25)
                     .all())

    return render_template('select_customer.html', customers=customers)


@app.route('/view_inventory')
def view_inventory():
    query = (request.args.get('q') or '').lower()
    inventory = item.query.all()

    if query:
        inventory = [
            it for it in inventory
            if query in it.name.lower() or (it.sku is not None and query in str(it.sku).lower())
        ]

    return render_template('view_inventory.html', inventory=inventory)


@app.route('/api/statements', methods=['GET'])
def api_statements_summary():
    """JSON summary for dashboards.
    Query params same as /statements (scope/year/month/start/end/phone).
    Returns: {range, totals, per_customer, per_day, per_month}
    """
    # Delegate date-range parsing to the /statements logic by reusing code
    scope = (request.args.get('scope') or 'custom').lower()
    phone = request.args.get('phone')
    today = datetime.now().date()
    if scope == 'year':
        year = int(request.args.get('year') or today.year)
        start_date = datetime(year, 1, 1).date()
        end_date = datetime(year, 12, 31).date()
    elif scope == 'month':
        year = int(request.args.get('year') or today.year)
        month = int(request.args.get('month') or today.month)
        start_date = datetime(year, month, 1).date()
        end_date = datetime(year, 12, 31).date() if month == 12 else (
                datetime(year, month + 1, 1).date() - timedelta(days=1))
    else:
        start_date = _parse_date(request.args.get('start'))
        end_date = _parse_date(request.args.get('end'))
        if not (start_date and end_date):
            return jsonify({"error": "Provide start and end in YYYY-MM-DD for custom scope"}), 400

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    q = (invoice.query
         .options(joinedload(invoice.customer))
         .join(customer, invoice.customerId == customer.id)
         .filter(invoice.isDeleted == False,
                 customer.isDeleted == False,
                 invoice.createdAt >= start_dt,
                 invoice.createdAt <= end_dt))

    if phone:
        q = q.filter(customer.phone == phone)
    invs = q.order_by(invoice.createdAt.asc()).all()

    totals = {
        "invoice_count": len(invs),
        "amount": round(sum((inv.totalAmount or 0) for inv in invs), 2)
    }

    per_customer = defaultdict(lambda: {"count": 0, "amount": 0.0})
    per_day = defaultdict(lambda: {"count": 0, "amount": 0.0})
    per_month = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for inv in invs:
        cust = inv.customer
        cust_key = f"{cust.name} ({cust.phone})" if cust else "Unknown"
        per_customer[cust_key]["count"] += 1
        per_customer[cust_key]["amount"] += (inv.totalAmount or 0)
        dkey = inv.createdAt.strftime('%Y-%m-%d')
        per_day[dkey]["count"] += 1
        per_day[dkey]["amount"] += (inv.totalAmount or 0)
        mkey = inv.createdAt.strftime('%Y-%m')
        per_month[mkey]["count"] += 1
        per_month[mkey]["amount"] += (inv.totalAmount or 0)

    # Convert defaultdicts to plain dicts for JSON
    return jsonify({
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "totals": totals,
        "per_customer": {k: {"count": v["count"], "amount": round(v["amount"], 2)} for k, v in per_customer.items()},
        "per_day": {k: {"count": v["count"], "amount": round(v["amount"], 2)} for k, v in per_day.items()},
        "per_month": {k: {"count": v["count"], "amount": round(v["amount"], 2)} for k, v in per_month.items()},
    })


@app.route('/api/statements/invoices', methods=['GET'])
def api_statements_invoices():
    """JSON: raw invoice rows with pagination (for tables/exports).
    Query params:
      scope/year/month/start/end/phone (same as above)
      page (default 1), per_page (default 50, max 500)
    """
    scope = (request.args.get('scope') or 'custom').lower()
    phone = request.args.get('phone')
    page = max(int(request.args.get('page', 1)), 1)
    per_page = min(max(int(request.args.get('per_page', 50)), 1), 500)

    today = datetime.now().date()
    if scope == 'year':
        year = int(request.args.get('year') or today.year)
        start_date = datetime(year, 1, 1).date()
        end_date = datetime(year, 12, 31).date()
    elif scope == 'month':
        year = int(request.args.get('year') or today.year)
        month = int(request.args.get('month') or today.month)
        start_date = datetime(year, month, 1).date()
        end_date = datetime(year, 12, 31).date() if month == 12 else (
                datetime(year, month + 1, 1).date() - timedelta(days=1))
    else:
        start_date = _parse_date(request.args.get('start'))
        end_date = _parse_date(request.args.get('end'))
        if not (start_date and end_date):
            return jsonify({"error": "Provide start and end in YYYY-MM-DD for custom scope"}), 400

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    q = (invoice.query
         .options(joinedload(invoice.customer))
         .join(customer, invoice.customerId == customer.id)
         .filter(invoice.isDeleted == False,
                 customer.isDeleted == False,
                 invoice.createdAt >= start_dt,
                 invoice.createdAt <= end_dt))

    if phone:
        q = q.filter(customer.phone == phone)

    total = q.count()
    invs = q.order_by(invoice.createdAt.asc()).offset((page - 1) * per_page).limit(per_page).all()

    rows = []
    for inv in invs:
        cust = inv.customer
        rows.append({
            "invoice_no": inv.invoiceId,
            "date": inv.createdAt.strftime('%Y-%m-%d'),
            "customer": cust.name if cust else 'Unknown',
            "phone": cust.phone if cust else '',
            "total": round(inv.totalAmount or 0, 2)
        })

    return jsonify({
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "total": total,
        "page": page,
        "per_page": per_page,
        "rows": rows
    })


@app.route('/statements/blank', methods=['GET'])
def statements_blank():
    return render_template(
        'statement.html',
        start_date=None,
        end_date=None,
        total_invoices=0,
        total_amount=0,
        phone=None,
        per_customer={},
        invs=[],
        scope='custom',
    )


@app.route('/create-bill', methods=['GET', 'POST'])
def start_bill():
    # --- GET: prefill if customer_id is supplied; otherwise show selector ---
    if request.method == 'GET':
        cid = request.args.get('customer_id', type=int)
        if cid:
            try:
                cust = (customer.query
                        .filter(customer.isDeleted == False, customer.id == cid)
                        .first())
            except Exception:
                cust = None
            if not cust:
                flash('Customer not found', 'warning')
                return redirect(url_for('about_user'))
            return render_template('create_bill.html', customer=cust,
                                   inventory=item.query.order_by(item.name.asc()).all())
        # GET: no customer_id, just render blank/new bill
        return render_template('create_bill.html')

    # POST logic
    # POST (A) select customer
    if 'description[]' not in request.form:
        selected_phone = request.form.get("customer") or request.form.get("customer_phone")
        sel = (customer.query
               .filter(customer.isDeleted == False, customer.phone == selected_phone)
               .first())
        if not sel:
            flash('Please pick a valid customer', 'warning')
            return render_template('select_customer.html')
        return render_template('create_bill.html', customer=sel, inventory=item.query.all())

    # (B) Final bill submission with line items
    selected_phone = request.form.get('customer_phone')
    selected_customer = customer.query.filter_by(phone=selected_phone).first()
    if not selected_customer:
        flash('Customer not found. Please reselect the customer.', 'warning')
        return render_template('select_customer.html')

    descriptions = request.form.getlist('description[]')
    quantities = request.form.getlist('quantity[]')
    rates = request.form.getlist('rate[]')
    dc_numbers = request.form.getlist('dc_no[]')  # may be [] if toggle off
    rounded_flags = request.form.getlist('rounded[]')

    # Get exclusion flags
    exclude_phone = bool(request.form.get('exclude_phone'))
    exclude_gst = bool(request.form.get('exclude_gst'))
    exclude_addr = bool(request.form.get('exclude_addr'))

    total = 0.0
    item_rows = []
    for i in range(len(descriptions)):
        desc = (descriptions[i] or '').strip()
        if not desc:
            continue
        qty = int(quantities[i]) if i < len(quantities) and quantities[i] else 0
        rate = float(rates[i]) if i < len(rates) and rates[i] else 0.0
        dc_val = ''
        if dc_numbers and i < len(dc_numbers) and dc_numbers[i]:
            dc_val = dc_numbers[i].strip()
        rounded = (i < len(rounded_flags) and rounded_flags[i] == "1")
        raw_total = qty * rate
        line_total = rounding_to_nearest_zero(raw_total) if rounded else raw_total
        total += line_total
        item_rows.append([desc, qty, rate, line_total, dc_val])

    # Create invoice
    new_invoice = invoice(
        customerId=selected_customer.id,
        createdAt=datetime.now(timezone.utc),
        totalAmount=(round(total, 2)),
        pdfPath="",  # set after inv_name built
        invoiceId="",  # temporary
        exclude_phone=exclude_phone,
        exclude_gst=exclude_gst,
        exclude_addr=exclude_addr
    )

    db.session.add(new_invoice)
    db.session.flush()
    # Add Alert - Not needed

    # Generate invoice Id + pdf path
    inv_name = f"SLP-{datetime.now().strftime('%d%m%y')}-{str(new_invoice.id).zfill(5)}"
    pdf_filename = f"{inv_name}.pdf"
    pdf_path = os.path.join("static/pdfs", pdf_filename)

    new_invoice.invoiceId = inv_name
    new_invoice.pdfPath = pdf_path
    db.session.flush()
    # add alerts - not needed as persistant on in place

    # Add line items
    for desc, qty, rate, line_total, dc_val in item_rows:
        matched_item = item.query.filter_by(name=desc).first()
        if matched_item:
            item_id = matched_item.id
        else:
            new_item = item(name=desc, unitPrice=rate, quantity=0, taxPercentage=0)
            db.session.add(new_item)
            db.session.flush()
            # add alert - not needed as persistent one in place
            item_id = new_item.id

        db.session.add(invoiceItem(
            invoiceId=new_invoice.id,
            itemId=item_id,
            quantity=qty,
            rate=rate,
            discount=0,
            taxPercentage=0,
            line_total=line_total,
            dcNo=(dc_val if dc_val else None)
        ))
    db.session.commit()

    # add alerts - Not needed, persistent one is in place

    # Did user include any DC values?
    # dc_present = any((x or '').strip() for x in (dc_numbers or []))

    # After successful creation, flash and redirect to locked preview page
    session['persistent_notice'] = f"Invoice {new_invoice.invoiceId} created successfully!"
    return redirect(url_for('view_bill_locked', invoicenumber=new_invoice.invoiceId, new_bill='True'))


@app.route('/view_customers', methods=['GET', 'POST'])
def view_customers():
    if request.method == 'POST':
        phone = request.form.get('customer')
        sel = (customer.query
               .filter(customer.isDeleted == False, customer.phone == phone)
               .first_or_404())
        return render_template('create_bill.html', customer=sel, inventory=item.query.all())

    query = (request.args.get('q') or '').strip().lower()
    q = (customer.query
         .filter(customer.isDeleted == False)
         .order_by(customer.createdAt.desc(), customer.id.desc()))
    customers = q.all()

    if query:
        customers = [
            c for c in customers
            if query in (c.company or '').lower()
               or query in (c.name or '').lower()
               or query in (c.phone or '')
        ]

    return render_template('view_customers.html', customers=customers)


@app.route('/view_bills')
def view_bills():
    """Render all bills with filtering, search, and sorting."""

    # ---- 1️⃣ Extract filters from query params ----
    query = (request.args.get('q') or '').lower()
    phone = request.args.get('phone')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # ---- 2️⃣ Base query with eager loading ----
    q = (
        invoice.query
        .options(joinedload(invoice.customer))
        .join(customer, invoice.customerId == customer.id)
        .filter(invoice.isDeleted == False, customer.isDeleted == False)
    )

    # ---- 3️⃣ Sorting ----
    sort_key = (request.args.get('sort') or 'date').lower()
    sort_dir = (request.args.get('dir') or 'desc').lower()

    def order(col):
        return col.desc() if sort_dir == 'desc' else col.asc()

    if sort_key == 'total':
        q = q.order_by(order(invoice.totalAmount))
    elif sort_key == 'invoice':
        q = q.order_by(order(invoice.invoiceId))
    elif sort_key == 'customer':
        q = q.order_by(order(customer.name))
    else:
        q = q.order_by(order(invoice.createdAt))

    # ---- 4️⃣ Optional date range filter ----
    try:
        if start_date and end_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            q = q.filter(invoice.createdAt >= start_dt, invoice.createdAt < end_dt)
    except Exception:
        pass

    # ---- 5️⃣ Execute main query ----
    invoices = q.all()

    # ---- 6️⃣ Transform for template ----
    bills = []
    for inv in invoices:
        cust = inv.customer
        bills.append({
            "invoice_no": inv.invoiceId,
            "date": inv.createdAt.strftime('%d-%b-%Y'),
            "customer_name": cust.name if cust else 'Unknown',
            "phone": cust.phone if cust else '',
            "total": f"{inv.totalAmount:,.2f}",
            "filename": f"{inv.invoiceId}.pdf",
            "customer_company": cust.company if cust else 'Unknown'
        })

    # ---- 7️⃣ Apply search filters ----
    if phone:
        bills = [b for b in bills if b['phone'] == phone]
    elif query:
        bills = [
            b for b in bills
            if query in b['customer_name'].lower()
               or query in b.get('phone', '')
               or query in b['invoice_no'].lower()
               or query in (b.get('customer_company') or '').lower()
        ]

    # ---- 8️⃣ Render ----
    return render_template('view_bills.html', bills=bills)


@app.route('/view-bill/<invoicenumber>')
def view_bill_locked(invoicenumber):
    # load invoice and related data
    current_invoice = invoice.query.filter_by(invoiceId=invoicenumber, isDeleted=False).first_or_404()
    cur_cust = customer.query.get(current_invoice.customerId)
    line_items = invoiceItem.query.filter_by(invoiceId=current_invoice.id).all()

    current_customer = {
        "name": cur_cust.name,
        "company": cur_cust.company,
        "phone": "Excluded in the bill" if current_invoice.exclude_phone else cur_cust.phone,
        "gst": "Excluded in the bill" if current_invoice.exclude_gst else cur_cust.gst,
        "address": "Excluded in the bill" if current_invoice.exclude_addr else cur_cust.address,
        "email": cur_cust.email
    }

    # build row wise lists for the template
    descriptions, quantities, rates, dc_numbers = [], [], [], []
    line_totals = []

    total = 0.0
    for li in line_items:
        itm = item.query.get(li.itemId)
        descriptions.append(itm.name if itm else 'Unknown')
        quantities.append(li.quantity)
        rates.append(li.rate)
        dc_numbers.append(li.dcNo or '')
        line_totals.append(li.line_total)
        total += li.line_total or 0

    # Determine whether to show DC column
    dcno = any((x or '').strip() for x in dc_numbers)

    new_bill = request.args.get('new_bill', '').lower() in ('yes', 'true', '1')
    back_to_select_customer = False  # avoid loop; use history back on client
    edit_bill = request.args.get('edit_bill', '').lower() in ('yes', 'true', '1')
    back_two_pages = edit_bill

    invoice_date = current_invoice.createdAt

    return render_template(
        'view_bill_locked.html',
        customer=current_customer,
        descriptions=descriptions,
        quantities=quantities,
        rates=rates,
        dc_numbers=dc_numbers,
        line_totals=line_totals,
        dcno=dcno,
        total=round(total, 2),
        invoice_no=current_invoice.invoiceId,
        new_bill=new_bill,
        back_to_select_customer=back_to_select_customer,
        customer_id=cur_cust.id,
        back_two_pages=back_two_pages,
        invoice_date=invoice_date,
    )


# amounts to words
# --- Amount to words (Indian numbering: Crore, Lakh, Thousand) ---
ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen"
]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digits(n: int) -> str:
    if n == 0:
        return ""
    if n < 20:
        return ONES[n]
    return (TENS[n // 10] + (" " + ONES[n % 10] if (n % 10) != 0 else "")).strip()


def _three_digits(n: int) -> str:
    # 0..999
    if n >= 100:
        rem = n % 100
        s = ONES[n // 100] + " Hundred"
        if rem:
            s += " and " + _two_digits(rem)
        return s
    return _two_digits(n)


def rupees_to_words(num: int) -> str:
    if num == 0:
        return "Zero"
    parts = []
    crore = num // 10000000;
    num %= 10000000
    lakh = num // 100000;
    num %= 100000
    thousand = num // 1000;
    num %= 1000
    rest = num  # 0..999

    # Use _three_digits for groups that can be up to 999
    if crore:
        parts.append(_three_digits(int(crore)) + " Crore")
    if lakh:
        parts.append(_three_digits(int(lakh)) + " Lakh")
    if thousand:
        parts.append(_three_digits(int(thousand)) + " Thousand")
    if rest:
        parts.append(_three_digits(int(rest)))

    return " ".join(parts)


def amount_to_words(amount) -> str:
    try:
        amt = float(amount or 0)
    except Exception:
        amt = 0.0
    rupees = int(amt)
    paise = int(round((amt - rupees) * 100))
    words = rupees_to_words(rupees) + " Rupees"
    if paise:
        words += " and " + _two_digits(paise) + " Paise"
    return words + " Only"


@app.route('/bill_preview/<invoicenumber>')
def bill_preview(invoicenumber):
    current_invoice = invoice.query.filter_by(invoiceId=invoicenumber, isDeleted=False).first_or_404()
    if not current_invoice:
        return f"No invoice found for {invoicenumber}"

    cur_cust = customer.query.get(current_invoice.customerId)

    current_customer = {
        "name": cur_cust.name,
        "company": cur_cust.company,
        "phone": None if current_invoice.exclude_phone else cur_cust.phone,
        "gst": None if current_invoice.exclude_gst else cur_cust.gst,
        "address": None if current_invoice.exclude_addr else cur_cust.address,
        "email": cur_cust.email
    }
    items = invoiceItem.query.filter_by(invoiceId=current_invoice.id).all()

    # Prepare item data
    item_data = []
    for i in items:
        item_name = item.query.get(i.itemId).name if i.itemId else "Unknown"
        entry = (
            item_name,
            "N/A",
            i.quantity,
            i.rate,
            i.discount,
            i.taxPercentage,
            i.line_total
        )
        item_data.append(entry)

    # DC numbers
    dc_numbers = [i.dcNo or '' for i in items]
    dcno = any(bool((x or '').strip()) for x in dc_numbers)

    config = layoutConfig().get_or_create()
    current_sizes = config.get_sizes()

    upi_id = APP_INFO["upi_info"]["upi_id"]
    company_name = APP_INFO["business"]["name"]
    upi_name = APP_INFO["upi_info"]["upi_name"]

    api_url = f"{request.host_url.rstrip('/')}/api/generate_upi_qr"
    params = {"upi_id": upi_id, "amount": current_invoice.totalAmount, "company_name": company_name}

    try:
        resp = requests.get(api_url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            qr_svg_base64 = data.get('qr_svg_base64')
            upi_url = data.get('upi_url')
        else:
            qr_svg_base64 = None
            upi_url = None
    except Exception as e:
        print(f"[ERROR] failed to fetch QR: {e}")
        qr_svg_base64 = None
        upi_url = None

    return render_template(
        'bill_preview.html',
        invoice=current_invoice,
        customer=current_customer,
        items=item_data,
        dcno=dcno,
        dc_numbers=dc_numbers,
        total_in_words=amount_to_words(current_invoice.totalAmount),
        sizes=current_sizes,
        qr_svg_base64=qr_svg_base64,
        upi_id=upi_id,
        upi_name=upi_name,
        company_name=company_name,
        total=current_invoice.totalAmount,
        app_info=APP_INFO,
    )


@app.route('/edit-bill/<invoicenumber>', methods=['GET', 'POST'])
def edit_bill(invoicenumber):
    # fetch invoice and related data
    current_invoice = invoice.query.filter_by(invoiceId=invoicenumber).first_or_404()
    current_customer = customer.query.get(current_invoice.customerId)
    line_items = invoiceItem.query.filter_by(invoiceId=current_invoice.id).all()

    # Build lists for template
    descriptions, quantities, rates, dc_numbers = [], [], [], []
    line_totals = []
    total = 0.0
    for li in line_items:
        itm = item.query.get(li.itemId)
        descriptions.append(itm.name if itm else 'Unknown')
        quantities.append(li.quantity)
        rates.append(li.rate)
        dc_numbers.append(li.dcNo or '')
        line_totals.append(li.line_total or 0)
        total += li.line_total or 0

    dcno = any((x or '').strip() for x in dc_numbers)

    prev_invoice_no = current_invoice.invoiceId
    try:
        prev_created_at = current_invoice.createdAt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        prev_created_at = str(current_invoice.createdAt)

    exclude_phone = current_invoice.exclude_phone
    exclude_gst = current_invoice.exclude_gst
    exclude_addr = current_invoice.exclude_addr

    # If POST: update invoice and redirect to view_bill_locked
    if request.method == 'POST':
        # Update customer-level metadata before saving invoice
        current_invoice.exclude_phone = request.form.get('exclude_phone') in ('on', 'true', '1')
        current_invoice.exclude_gst = request.form.get('exclude_gst') in ('on', 'true', '1')
        current_invoice.exclude_addr = request.form.get('exclude_addr') in ('on', 'true', '1')
        db.session.commit()
        # add alert - Not needed funcionally
        return redirect(url_for('view_bill_locked', invoicenumber=current_invoice.invoiceId, edit_bill='true'))

    # Render the same template as create_bill.html but pre-filled
    return render_template(
        'create_bill.html',
        customer=current_customer,
        inventory=item.query.all(),
        success=False,  # show filled rows
        descriptions=descriptions,
        quantities=quantities,
        rates=rates,
        dc_numbers=dc_numbers,
        dcno=dcno,
        total=round(total, 2),
        grand_total=round(total, 2),
        invoice_no=current_invoice.invoiceId,
        edit_mode=True,  # flag to distinguish editing vs new bill
        prev_invoice_no=prev_invoice_no,
        prev_created_at=prev_created_at,
        exclude_phone=exclude_phone,
        exclude_gst=exclude_gst,
        exclude_addr=exclude_addr,
        line_totals=line_totals,
    )


@app.route('/delete-bill/<invoicenumber>', methods=['POST'])
def delete_bill(invoicenumber):
    inv = invoice.query.filter_by(invoiceId=invoicenumber, isDeleted=False).first_or_404()
    inv.isDeleted = True
    inv.deletedAt = datetime.now(timezone.utc)
    db.session.commit()
    # add alert
    flash('Bill has been deleted.', 'danger')

    next_url = request.form.get('next') or ''
    try:
        host = urlparse(request.host_url).netloc
        parsed = urlparse(next_url)
        if next_url and (parsed.netloc == '' or parsed.netloc == host):
            return redirect(next_url)
    except Exception:
        pass
    return redirect(url_for('view_bills'))


@app.route('/update-bill/<invoicenumber>', methods=['POST'])
def update_bill(invoicenumber):
    # 1) Load the invoice being edited
    current_invoice = invoice.query.filter_by(invoiceId=invoicenumber, isDeleted=False).first_or_404()
    current_customer = customer.query.get(current_invoice.customerId)

    # 2) Read form inputs
    descriptions = request.form.getlist('description[]')
    quantities = request.form.getlist('quantity[]')
    rates = request.form.getlist('rate[]')
    dc_numbers = request.form.getlist('dc_no[]')  # may be empty if toggle off
    rounded_flags = request.form.getlist('rounded[]')

    # 3) Normalize rows + recompute totals
    rows = []
    total = 0.0
    for i in range(len(descriptions)):
        desc = (descriptions[i] or '').strip()
        if not desc:
            continue  # skip empty rows

        qty = int(quantities[i]) if i < len(quantities) and quantities[i] else 0
        rate = float(rates[i]) if i < len(rates) and rates[i] else 0.0
        dc = (dc_numbers[i].strip() if i < len(dc_numbers) and dc_numbers[i] else None)
        rounded = (i < len(rounded_flags) and rounded_flags[i] == "1")
        raw_total = qty * rate
        line_total = rounding_to_nearest_zero(raw_total) if rounded else raw_total
        total += line_total
        rows.append((desc, qty, rate, dc, line_total))

    # 4) Replace all existing line items with the new set using ORM deletes so sync events fire
    existing_items = invoiceItem.query.filter_by(invoiceId=current_invoice.id).all()
    for existing_item in existing_items:
        db.session.delete(existing_item)
    db.session.flush()

    for desc, qty, rate, dc, line_total in rows:
        # Reuse existing item by name, or create a placeholder item if not found
        matched_item = item.query.filter_by(name=desc).first()
        if matched_item:
            item_id = matched_item.id
        else:
            new_item = item(name=desc, unitPrice=rate, quantity=0, taxPercentage=0)
            db.session.add(new_item)
            db.session.flush()
            item_id = new_item.id

        db.session.add(invoiceItem(
            invoiceId=current_invoice.id,
            itemId=item_id,
            quantity=qty,
            rate=rate,
            discount=0,
            taxPercentage=0,
            line_total=line_total,
            dcNo=dc if dc else None
        ))

    # 5) Update invoice total (and updatedAt if you have it)
    current_invoice.totalAmount = (round(total, 2))

    # 5.5) Update customer-level metadata before saving invoice
    current_invoice.exclude_phone = request.form.get('exclude_phone') in ('on', 'true', '1')
    current_invoice.exclude_gst = request.form.get('exclude_gst') in ('on', 'true', '1')
    current_invoice.exclude_addr = request.form.get('exclude_addr') in ('on', 'true', '1')

    db.session.commit()
    # add alert - not needed persistent one in place

    # 6) Redirect to locked preview after update
    session['persistent_notice'] = f"Old invoice {current_invoice.invoiceId} updated successfully!"

    return redirect(url_for('view_bill_locked', invoicenumber=current_invoice.invoiceId, edit_bill='true'))


@app.route('/bill_preview/latest')
def latest_bill_preview():
    current_invoice = (
        invoice.query
        .filter(invoice.isDeleted == False)
        .order_by(invoice.id.desc())
        .first()
    )
    if not current_invoice:
        return "No invoice found"

    cur_cust = customer.query.get(current_invoice.customerId)

    current_customer = {
        "name": cur_cust.name,
        "company": cur_cust.company,
        "phone": None if current_invoice.exclude_phone else cur_cust.phone,
        "gst": None if current_invoice.exclude_gst else cur_cust.gst,
        "address": None if current_invoice.exclude_addr else cur_cust.address,
        "email": cur_cust.email
    }

    items = invoiceItem.query.filter_by(invoiceId=current_invoice.id).all()
    item_data = []

    for i in items:
        item_name = item.query.get(i.itemId).name if i.itemId else "Unknown"
        entry = (
            item_name,
            "N/A",
            i.quantity,
            i.rate,
            i.discount,
            i.taxPercentage,
            i.line_total
        )
        item_data.append(entry)

    config = layoutConfig.get_or_create()
    current_sizes = config.get_sizes()

    dc_numbers = [i.dcNo or '' for i in items]
    dcno = any(bool((x or '').strip()) for x in dc_numbers)

    # 🔹 UPI QR generation (same as main bill_preview route)
    upi_id = APP_INFO["upi_info"]["upi_id"]
    company_name = APP_INFO["business"]["name"]
    upi_name = APP_INFO["upi_info"]["upi_name"]

    api_url = f"{request.host_url.rstrip('/')}/api/generate_upi_qr"
    params = {
        "upi_id": upi_id,
        "amount": current_invoice.totalAmount,
        "company_name": company_name
    }

    try:
        resp = requests.get(api_url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            qr_svg_base64 = data.get('qr_svg_base64')
            upi_url = data.get('upi_url')
        else:
            qr_svg_base64 = None
            upi_url = None
    except Exception as e:
        print(f"[ERROR] failed to fetch QR: {e}")
        qr_svg_base64 = None
        upi_url = None

    return render_template(
        'bill_preview.html',
        invoice=current_invoice,
        customer=current_customer,
        items=item_data,
        dcno=dcno,
        dc_numbers=dc_numbers,
        total_in_words=amount_to_words(current_invoice.totalAmount),
        sizes=current_sizes,
        app_info=APP_INFO,
        qr_svg_base64=qr_svg_base64,
        upi_id=upi_id,
        upi_name=upi_name,
        company_name=company_name,
        total=current_invoice.totalAmount
    )


# --- Common builder for sample invoice context ---

def _build_sample_invoice_context():
    # Get the most recent invoice
    recent_invoice = invoice.query.order_by(invoice.createdAt.desc()).first()

    if not recent_invoice:
        # Fallback if no invoice exists
        fallback_created_at = datetime.now(timezone.utc).replace(tzinfo=None)
        return {
            "invoice": type("Invoice", (),
                            {"invoiceId": "NO_DATA", "createdAt": fallback_created_at, "totalAmount": 0.0})(),
            "customer": {},
            "items": [],
            "dcno": False,
            "dc_numbers": [],
            "total_in_words": "",
            "sizes": layoutConfig().get_or_create().get_sizes(),
            "rows": 0,
            "persistent_notice": session.get("persistent_notice"),
        }

    # Get customer info
    cust = customer.query.get(recent_invoice.customerId)

    # Get items from invoiceItem joined with item
    line_items = invoiceItem.query.filter_by(invoiceId=recent_invoice.id).all()
    items = []
    for li in line_items:
        itm = item.query.get(li.itemId)
        items.append({
            "name": itm.name if itm else "Unknown",
            "hsn": "N/A",
            "qty": li.quantity,
            "rate": li.rate,
            "discount": li.discount,
            "tax": li.taxPercentage,
            "amount": li.line_total
        })

    sample_items = [
        (i["name"], i["hsn"], i["qty"], i["rate"], i["discount"], i["tax"], i["amount"])
        for i in items
    ]

    # Delivery challan toggle
    dcno = session.get("dc_enabled", False)
    dc_numbers = [i.dc_number for i in items if hasattr(i, "dc_number")] if dcno else []

    # Layout sizes
    current_sizes = layoutConfig().get_or_create().get_sizes()

    return {
        "invoice": recent_invoice,
        "customer": {
            "company": getattr(cust, "company", ""),
            "address": getattr(cust, "address", ""),
            "gst": getattr(cust, "gst", ""),
            "phone": getattr(cust, "phone", ""),
            "email": getattr(cust, "email", ""),
        },
        "items": sample_items,
        "dcno": dcno,
        "dc_numbers": dc_numbers,
        "total_in_words": recent_invoice.total_in_words if hasattr(recent_invoice, "total_in_words") else "",
        "sizes": current_sizes,
        "rows": len(sample_items),
        "persistent_notice": session.get("persistent_notice"),
    }


# --- Unified Layout Handler ---
def handle_layout(action=None, data=None):
    config = layoutConfig().get_or_create()
    updated = False

    if action == "update" and data:
        current_sizes = config.get_sizes()
        updated = False
        for k in ["header", "customer", "table", "totals", "payment", "footer", "invoice_info"]:
            if k in data:
                try:
                    new_size = int(data[k])
                    if current_sizes.get(k) != new_size:
                        current_sizes[k] = new_size
                        updated = True
                except Exception:
                    pass
        if updated:
            config.set_sizes(current_sizes)
            db.session.commit()
            session['persistent_notice'] = "Layout has been updated successfully!"

    elif action == "reset":
        config.reset_sizes()
        db.session.commit()
        session['persistent_notice'] = "Layout has been reset to defaults!"

    return _build_sample_invoice_context()


# --- Routes ---
@app.route('/test-pre-preview', methods=['GET', 'POST'])
def test_pre_preview():
    upi_id = APP_INFO["upi_info"]["upi_id"]
    company_name = APP_INFO["business"]["name"]
    upi_name = APP_INFO["upi_info"]["upi_name"]

    api_url = f"{request.host_url.rstrip('/')}/api/generate_upi_qr"
    params = {"upi_id": upi_id, "amount": "", "company_name": company_name}  # amount empty for preview

    try:
        resp = requests.get(api_url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            upi_qr = data.get('qr_svg_base64')
        else:
            upi_qr = None
    except Exception as e:
        print(f"[ERROR] Failed to fetch QR for preview: {e}")
        upi_qr = None

    ctx = handle_layout(action="view")
    return render_template(
        'pre-preview-bill.html',
        app_info=APP_INFO,
        upi_qr=upi_qr,
        **ctx
    )


@app.route('/pre-pre-preview', methods=['GET'])
def test_pre_preview_():
    try:
        if session['persistent_notice']:
            pass  # keep notice, just no backup check
    except Exception:
        pass
    ctx = handle_layout(action="view")
    return render_template("pre-preview-bill.html", app_info=APP_INFO, **ctx)


@app.route('/update-layout', methods=['POST'])
def update_layout():
    data = request.get_json(force=True) if request.is_json else request.form
    ctx = handle_layout(action="update", data=data)
    return render_template("pre-preview-bill.html", **ctx)


@app.route('/reset-layout', methods=['POST'])
def reset_layout():
    ctx = handle_layout(action="reset")
    return render_template("pre-preview-bill.html", **ctx)


app.jinja_env.globals.update(zip=zip)


@app.route('/statements', methods=['GET'])
def statements():
    """
    Render customer statements for a date range or customer, with export (HTML, CSV, PDF/Print).
    Query params:
      - scope: 'year'/'month'/'custom'
      - year/month/start/end
      - phone: filter by customer phone
      - export: 'csv' or 'pdf' (default: html)
    """
    scope = (request.args.get('scope') or 'custom').lower()
    phone = request.args.get('phone')
    export = (request.args.get('export') or '').lower()

    today = datetime.now().date()
    min_allowed_start = get_default_statement_start().date()  # 🔹 Lower limit from info.json

    # 🔸 Resolve start/end based on scope
    if scope == 'year':
        year = int(request.args.get('year') or today.year)
        start_date = datetime(year, 1, 1).date()
        end_date = datetime(year, 12, 31).date()
    elif scope == 'month':
        year = int(request.args.get('year') or today.year)
        month = int(request.args.get('month') or today.month)
        start_date = datetime(year, month, 1).date()
        end_date = datetime(year, 12, 31).date() if month == 12 else (
                datetime(year, month + 1, 1).date() - timedelta(days=1))
    else:
        start_date = _parse_date(request.args.get('start'))
        end_date = _parse_date(request.args.get('end'))
        # Fallback: default to current month
        if not (start_date and end_date):
            start_date = today.replace(day=1)
            end_date = today

    # 🔸 Enforce lower date limit
    if start_date < min_allowed_start:
        start_date = min_allowed_start

    # Normalize datetimes
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    # 🔹 Query invoices
    q = (
        invoice.query
        .options(joinedload(invoice.customer))
        .join(customer, invoice.customerId == customer.id)
        .filter(
            invoice.isDeleted == False,
            customer.isDeleted == False,
            invoice.createdAt >= start_dt,
            invoice.createdAt <= end_dt,
        )
    )
    if phone:
        q = q.filter(customer.phone == phone)

    invs = q.order_by(invoice.createdAt.asc()).all()

    # 🔹 Aggregations
    total_invoices = len(invs)
    total_amount = round(sum((inv.totalAmount or 0) for inv in invs), 2)
    per_customer = defaultdict(lambda: {"count": 0, "amount": 0.0, "company": None, "phone": None})

    for inv in invs:
        cust = inv.customer
        if cust:
            key = cust.phone
            per_customer[key]["count"] += 1
            per_customer[key]["amount"] += (inv.totalAmount or 0)
            per_customer[key]["company"] = cust.company
            per_customer[key]["phone"] = cust.phone
        else:
            per_customer["Unknown"]["count"] += 1
            per_customer["Unknown"]["amount"] += (inv.totalAmount or 0)

    if not per_customer:
        per_customer = {}

    # 🔸 Export CSV
    if export == "csv":
        output = io.StringIO()
        writer = csv.writer(output)

        biz = APP_INFO.get("business", {})
        bank = APP_INFO.get("bank", {})
        statement_meta = APP_INFO.get("statement", {})

        writer.writerow(
            [f"{biz.get('name', 'Business Name')} - {statement_meta.get('header_title', 'Statement Summary')}"])
        writer.writerow(["Generated On", datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        writer.writerow(["Period", f"{start_date.strftime('%d %B %Y')} to {end_date.strftime('%d %B %Y')}"])
        writer.writerow([])

        writer.writerow(["Invoice No", "Date", "Company", "Phone", "Amount (INR)"])
        for inv in invs:
            cust = inv.customer
            writer.writerow([
                inv.invoiceId,
                inv.createdAt.strftime('%d %B %Y'),
                cust.company if cust else '',
                cust.phone if cust else '',
                f"{inv.totalAmount:,.2f}"
            ])

        writer.writerow([])
        writer.writerow(["Summary"])
        writer.writerow(["Total Invoices", total_invoices])
        writer.writerow(["Total Amount (INR)", f"{total_amount:,.2f}"])
        writer.writerow([])

        if per_customer:
            writer.writerow(["Per Customer Summary"])
            writer.writerow(["Phone", "Company", "Invoice Count", "Total Amount (INR)"])
            for key, val in per_customer.items():
                writer.writerow([
                    val.get("phone", key),
                    val.get("company", ""),
                    val.get("count", 0),
                    f"{val.get('amount', 0):,.2f}"
                ])
            writer.writerow([])

        writer.writerow(["Payment Information"])
        writer.writerow(["Account Name", bank.get("account_name", "")])
        writer.writerow(["Bank", f"{bank.get('bank_name', '')}, {bank.get('branch', '')}"])
        writer.writerow(["Account Number", bank.get("account_number", "")])
        writer.writerow(["IFSC", bank.get("ifsc", "")])
        writer.writerow(["PhonePe/GPay", biz.get("upi_id", "")])
        writer.writerow([])

        writer.writerow(["Disclaimer", statement_meta.get("disclaimer", "This is a system-generated statement.")])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment;filename=statements_{start_date}_{end_date}.csv"}
        )

    # 🔸 Export XLSX
    if export == "xlsx":
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, NamedStyle, numbers
        from openpyxl.utils import get_column_letter
        from io import BytesIO

        wb = openpyxl.Workbook()
        ws_inv = wb.active
        ws_inv.title = "Invoices"

        # Header row
        headers = ["Invoice No", "Date", "Company", "Phone", "Amount (INR)"]
        header_font = Font(bold=True)
        header_fill = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center")
        for col_num, col_name in enumerate(headers, 1):
            cell = ws_inv.cell(row=1, column=col_num, value=col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align

        # Data rows
        currency_fmt = u'INR #,##0.00'
        for row_num, inv in enumerate(invs, 2):
            cust = inv.customer
            ws_inv.cell(row=row_num, column=1, value=inv.invoiceId)
            ws_inv.cell(row=row_num, column=2, value=inv.createdAt.strftime('%d %B %Y'))
            ws_inv.cell(row=row_num, column=3, value=cust.company if cust else '')
            ws_inv.cell(row=row_num, column=4, value=cust.phone if cust else '')
            amt_cell = ws_inv.cell(row=row_num, column=5, value=round(inv.totalAmount or 0, 2))
            amt_cell.number_format = currency_fmt
            amt_cell.alignment = Alignment(horizontal="right")

        # Auto-size columns for "Invoices"
        for col in ws_inv.columns:
            max_length = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                try:
                    val = str(cell.value) if cell.value is not None else ""
                    max_length = max(max_length, len(val))
                except Exception:
                    pass
            ws_inv.column_dimensions[col_letter].width = min(max_length + 2, 40)

        # Add "Summary" sheet
        ws_sum = wb.create_sheet("Summary")
        row = 1
        bold = Font(bold=True)
        # Title
        biz = APP_INFO.get("business", {})
        bank = APP_INFO.get("bank", {})
        statement_meta = APP_INFO.get("statement", {})
        ws_sum.cell(row=row, column=1,
                    value=f"{biz.get('name', 'Business Name')} - {statement_meta.get('header_title', 'Statement Summary')}").font = bold
        row += 1
        ws_sum.cell(row=row, column=1, value="Generated On")
        ws_sum.cell(row=row, column=2, value=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        row += 1
        ws_sum.cell(row=row, column=1, value="Period")
        ws_sum.cell(row=row, column=2, value=f"{start_date.strftime('%d %B %Y')} to {end_date.strftime('%d %B %Y')}")
        row += 2
        ws_sum.cell(row=row, column=1, value="Summary").font = bold
        row += 1
        ws_sum.cell(row=row, column=1, value="Total Invoices")
        ws_sum.cell(row=row, column=2, value=total_invoices)
        row += 1
        ws_sum.cell(row=row, column=1, value="Total Amount (INR)")
        amt_cell = ws_sum.cell(row=row, column=2, value=total_amount)
        amt_cell.number_format = currency_fmt
        row += 2

        # Per-customer summary
        if per_customer:
            ws_sum.cell(row=row, column=1, value="Per Customer Summary").font = bold
            row += 1
            ws_sum.cell(row=row, column=1, value="Phone").font = bold
            ws_sum.cell(row=row, column=2, value="Company").font = bold
            ws_sum.cell(row=row, column=3, value="Invoice Count").font = bold
            ws_sum.cell(row=row, column=4, value="Total Amount (INR)").font = bold
            row += 1
            for key, val in per_customer.items():
                ws_sum.cell(row=row, column=1, value=val.get("phone", key))
                ws_sum.cell(row=row, column=2, value=val.get("company", ""))
                ws_sum.cell(row=row, column=3, value=val.get("count", 0))
                amt_cell = ws_sum.cell(row=row, column=4, value=round(val.get("amount", 0), 2))
                amt_cell.number_format = currency_fmt
                row += 1
            row += 1

        # Payment Information
        ws_sum.cell(row=row, column=1, value="Payment Information").font = bold
        row += 1
        ws_sum.cell(row=row, column=1, value="Account Name")
        ws_sum.cell(row=row, column=2, value=bank.get("account_name", ""))
        row += 1
        ws_sum.cell(row=row, column=1, value="Bank")
        ws_sum.cell(row=row, column=2, value=f"{bank.get('bank_name', '')}, {bank.get('branch', '')}")
        row += 1
        ws_sum.cell(row=row, column=1, value="Account Number")
        ws_sum.cell(row=row, column=2, value=bank.get("account_number", ""))
        row += 1
        ws_sum.cell(row=row, column=1, value="IFSC")
        ws_sum.cell(row=row, column=2, value=bank.get("ifsc", ""))
        row += 1
        ws_sum.cell(row=row, column=1, value="PhonePe/GPay")
        ws_sum.cell(row=row, column=2, value=biz.get("upi_id", ""))
        row += 2
        ws_sum.cell(row=row, column=1, value="Disclaimer")
        ws_sum.cell(row=row, column=2, value=statement_meta.get("disclaimer", "This is a system-generated statement."))

        # Auto-size columns for "Summary"
        for col in ws_sum.columns:
            max_length = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                try:
                    val = str(cell.value) if cell.value is not None else ""
                    max_length = max(max_length, len(val))
                except Exception:
                    pass
            ws_sum.column_dimensions[col_letter].width = min(max_length + 2, 50)

        # --- Reorder sheets: Summary first, Invoices second ---
        wb._sheets = [ws_sum, ws_inv]

        # Write to BytesIO and return as response
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        filename = f"statements_{start_date}_{end_date}.xlsx"
        return Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )

    # 🔸 Export PDF (Flask HTML version, consistent with company statements)
    if export == "pdf":
        return render_template(
            'print_statement.html',
            start_date=start_date,
            end_date=end_date,
            total_invoices=total_invoices,
            total_amount=round(total_amount, 2),
            inv_rows=[
                {
                    "invoice_no": inv.invoiceId,
                    "date": inv.createdAt.strftime('%Y-%m-%d'),
                    "total": float(inv.totalAmount or 0),
                    "company": inv.customer.company if inv.customer else "(No Company)",
                    "phone": inv.customer.phone if inv.customer else "(No Phone)",
                }
                for inv in invs
            ],
            per_customer=per_customer,
            phone=phone,
            date_wise=True,
            APP_INFO=APP_INFO,
        )

    # 🔸 Default: HTML View
    return render_template(
        'statement.html',
        start_date=start_date,
        end_date=end_date,
        total_invoices=total_invoices,
        total_amount=total_amount,
        phone=phone,
        per_customer=per_customer,
        invs=invs,
        scope=scope,
    )


@app.route('/statements_company', methods=['GET', 'POST'])
def statements_company():
    """
    Generate HTML/CSV statements filtered by company name or phone number.
    Enhancements:
    - Unified date range parsing (with safe defaults)
    - Uses joinedload for performance
    - Adds graceful handling when no results or invalid input
    - Consistent CSV formatting with per-company totals
    - Improved suggestions list
    """

    # --- Query params ---
    query = (request.args.get('query') or '').strip()
    # Support both legacy 'fmt' and new 'format' param for export type
    fmt = (request.args.get('format') or request.args.get('fmt') or 'html').lower()
    start = request.args.get('start')
    end = request.args.get('end')
    phone = (request.args.get('phone') or '').strip()

    today = datetime.now(timezone.utc).date()
    start_dt = datetime(today.year, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime.now(timezone.utc)

    # --- Parse date range if provided ---
    if start and end:
        try:
            start_dt = datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            end_dt = datetime.strptime(end, '%Y-%m-%d').replace(tzinfo=timezone.utc) + timedelta(days=1) - timedelta(
                seconds=1)
            # 🔹 Enforce lower limit from info.json
            min_allowed_start = get_default_statement_start()
            if start_dt < min_allowed_start:
                start_dt = min_allowed_start
        except Exception:
            pass
    else:
        start_dt = get_default_statement_start()

    # --- Suggestions for autocomplete ---
    suggestions = []
    try:
        suggestions = [
            {"company": c.company or "", "phone": c.phone}
            for c in customer.query.filter(customer.isDeleted == False).all()
            if (c.company or c.phone)
        ]
    except Exception as e:
        print("[warn] Failed to load suggestions:", e)

    invs = []
    total_invoices = 0
    total_amount = 0.0

    # --- Query invoices if search provided ---
    if phone:
        # If phone is provided, search by exact phone
        q = (
            invoice.query
            .options(joinedload(invoice.customer))
            .join(customer, invoice.customerId == customer.id)
            .filter(
                invoice.isDeleted == False,
                customer.isDeleted == False,
                invoice.createdAt >= start_dt,
                invoice.createdAt <= end_dt,
                customer.phone == phone
            )
        )
        invs = q.order_by(invoice.createdAt.desc()).all()
        total_invoices = len(invs)
        total_amount = sum(float(inv.totalAmount or 0) for inv in invs)
    elif query:
        # Fallback: fuzzy search by company or phone (legacy)
        q = (
            invoice.query
            .options(joinedload(invoice.customer))
            .join(customer, invoice.customerId == customer.id)
            .filter(
                invoice.isDeleted == False,
                customer.isDeleted == False,
                invoice.createdAt >= start_dt,
                invoice.createdAt <= end_dt,
                or_(
                    func.lower(customer.company).like(f"%{query.lower()}%"),
                    customer.phone == query
                )
            )
        )
        invs = q.order_by(invoice.createdAt.desc()).all()
        total_invoices = len(invs)
        total_amount = sum(float(inv.totalAmount or 0) for inv in invs)

    # --- CSV Export ---
    if fmt == 'csv' and (phone or query):
        buf = io.StringIO()
        writer = csv.writer(buf)

        # Prepare header values
        customer_company = ''
        customer_phone = ''
        if invs and invs[0].customer:
            customer_company = invs[0].customer.company or ''
            customer_phone = invs[0].customer.phone or ''

        # Header
        writer.writerow([f"{APP_INFO['business']['name']} - Customer Statement"])
        writer.writerow(["Generated On", datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        writer.writerow(["Customer Name", customer_company])
        writer.writerow(["Customer Phone", customer_phone])
        writer.writerow(["Period", f"{start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}"])
        writer.writerow([])

        # Table (remove Company and Phone columns; they are shown in header)
        writer.writerow(["Invoice No", "Date", "Total (INR)"])
        for inv in invs:
            writer.writerow([
                inv.invoiceId,
                inv.createdAt.strftime('%Y-%m-%d'),
                f"{float(inv.totalAmount or 0):.2f}"
            ])

        # Summary
        writer.writerow([])
        writer.writerow(["Summary"])
        writer.writerow(["Total Invoices", total_invoices])
        writer.writerow(["Total Amount (INR)", f"{total_amount:.2f}"])
        writer.writerow([])

        # Payment Info (static for now)
        writer.writerow(["Payment Information"])
        writer.writerow(["Account Name", APP_INFO["bank"]["account_name"]])
        writer.writerow(["Bank", f"{APP_INFO['bank']['bank_name']}, {APP_INFO['bank']['branch']}"])
        writer.writerow(["Account Number", APP_INFO["bank"]["account_number"]])
        writer.writerow(["IFSC", APP_INFO["bank"]["ifsc"]])
        writer.writerow(["PhonePe/GPay", APP_INFO["bank"]["bhim"]])
        writer.writerow([])

        writer.writerow(["Disclaimer", "This is a system-generated statement. No signature required."])

        safe_company = (customer_company or "company").replace(" ", "_").replace("/", "_")
        filename = f"{safe_company}_{datetime.now().strftime('%Y-%m-%d')}_statement.csv"

        return Response(
            buf.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )

    # --- XLSX Export ---
    if fmt == 'xlsx' and (phone or query):
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill
        from openpyxl.utils import get_column_letter
        from io import BytesIO

        wb = openpyxl.Workbook()
        ws_sum = wb.active
        ws_sum.title = "Summary"
        ws_inv = wb.create_sheet("Invoices")

        biz = APP_INFO.get("business", {})
        bank = APP_INFO.get("bank", {})
        statement_meta = APP_INFO.get("statement", {})

        # Prepare header values
        customer_company = ''
        customer_phone = ''
        if invs and invs[0].customer:
            customer_company = invs[0].customer.company or ''
            customer_phone = invs[0].customer.phone or ''

        # --- Summary Sheet ---
        bold = Font(bold=True)
        currency_fmt = u'INR #,##0.00'
        row = 1
        ws_sum.cell(row=row, column=1,
                    value=f"{biz.get('name', 'Business')} - {statement_meta.get('header_title', 'Customer Statement')}").font = bold
        row += 1
        ws_sum.cell(row=row, column=1, value="Generated On")
        ws_sum.cell(row=row, column=2, value=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        row += 1
        ws_sum.cell(row=row, column=1, value="Customer Name")
        ws_sum.cell(row=row, column=2, value=customer_company)
        row += 1
        ws_sum.cell(row=row, column=1, value="Customer Phone")
        ws_sum.cell(row=row, column=2, value=customer_phone)
        row += 1
        ws_sum.cell(row=row, column=1, value="Period")
        ws_sum.cell(row=row, column=2, value=f"{start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")
        row += 2
        ws_sum.cell(row=row, column=1, value="Summary").font = bold
        row += 1
        ws_sum.cell(row=row, column=1, value="Total Invoices")
        ws_sum.cell(row=row, column=2, value=total_invoices)
        row += 1
        ws_sum.cell(row=row, column=1, value="Total Amount (INR)")
        amt_cell = ws_sum.cell(row=row, column=2, value=round(total_amount, 2))
        amt_cell.number_format = currency_fmt
        row += 2
        ws_sum.cell(row=row, column=1, value="Payment Information").font = bold
        row += 1
        ws_sum.cell(row=row, column=1, value="Account Name")
        ws_sum.cell(row=row, column=2, value=bank.get("account_name", ""))
        row += 1
        ws_sum.cell(row=row, column=1, value="Bank")
        ws_sum.cell(row=row, column=2, value=f"{bank.get('bank_name', '')}, {bank.get('branch', '')}")
        row += 1
        ws_sum.cell(row=row, column=1, value="Account Number")
        ws_sum.cell(row=row, column=2, value=bank.get("account_number", ""))
        row += 1
        ws_sum.cell(row=row, column=1, value="IFSC")
        ws_sum.cell(row=row, column=2, value=bank.get("ifsc", ""))
        row += 1
        ws_sum.cell(row=row, column=1, value="PhonePe/GPay")
        ws_sum.cell(row=row, column=2, value=biz.get("upi_id", ""))
        row += 2
        ws_sum.cell(row=row, column=1, value="Disclaimer")
        ws_sum.cell(row=row, column=2, value=statement_meta.get("disclaimer", "This is a system-generated statement."))

        # Auto-size columns for summary
        for col in ws_sum.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = str(cell.value) if cell.value else ""
                max_len = max(max_len, len(val))
            ws_sum.column_dimensions[col_letter].width = min(max_len + 2, 50)

        # --- Invoices Sheet ---
        headers = ["Invoice No", "Date", "Total (INR)"]
        header_font = Font(bold=True)
        header_fill = PatternFill(start_color="E8E8E8", end_color="E8E8E8", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center")

        for col_num, col_name in enumerate(headers, 1):
            c = ws_inv.cell(row=1, column=col_num, value=col_name)
            c.font = header_font
            c.fill = header_fill
            c.alignment = header_align

        for row_num, inv in enumerate(invs, 2):
            ws_inv.cell(row=row_num, column=1, value=inv.invoiceId)
            ws_inv.cell(row=row_num, column=2, value=inv.createdAt.strftime('%Y-%m-%d'))
            amt_cell = ws_inv.cell(row=row_num, column=3, value=round(inv.totalAmount or 0, 2))
            amt_cell.number_format = currency_fmt
            amt_cell.alignment = Alignment(horizontal="right")

        for col in ws_inv.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = str(cell.value) if cell.value else ""
                max_len = max(max_len, len(val))
            ws_inv.column_dimensions[col_letter].width = min(max_len + 2, 40)

        # Set sheet order
        wb._sheets = [ws_sum, ws_inv]

        # Output response
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        safe_company = (customer_company or "company").replace(" ", "_").replace("/", "_")
        filename = f"{safe_company}_{datetime.now().strftime('%Y-%m-%d')}_statement.xlsx"
        return Response(
            buf.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )

    customer_company = ''
    customer_phone = ''
    if invs and invs[0].customer:
        customer_company = invs[0].customer.company or ''
        customer_phone = invs[0].customer.phone or ''

    # --- PDF Export ---
    if fmt == 'pdf' and (phone or query):
        # Use print-friendly HTML template for print preview
        return render_template(
            'print_statement.html',
            query=query,
            start_date=start_dt.date(),
            end_date=end_dt.date(),
            total_invoices=total_invoices,
            total_amount=round(total_amount, 2),
            inv_rows=[
                {
                    "invoice_no": inv.invoiceId,
                    "date": inv.createdAt.strftime('%Y-%m-%d'),
                    "total": float(inv.totalAmount or 0),
                }
                for inv in invs
            ],
            suggestions=suggestions,
            request=request,
            customer_company=customer_company,
            customer_phone=customer_phone,
            company_wise=True,
            APP_INFO=APP_INFO,
        )

    # --- Build rows for HTML template ---
    inv_rows = []
    for inv in invs:
        inv_rows.append({
            "invoice_no": inv.invoiceId,
            "date": inv.createdAt.strftime('%Y-%m-%d'),
            "total": float(inv.totalAmount or 0),
        })

    # --- Render HTML ---
    return render_template(
        'statements_company.html',
        query=query,
        start_date=start_dt.date(),
        end_date=end_dt.date(),
        total_invoices=total_invoices,
        total_amount=round(total_amount, 2),
        inv_rows=inv_rows,
        suggestions=suggestions,
        request=request,
        customer_company=customer_company,
        customer_phone=customer_phone,
    )


@app.route('/qr_code', methods=['GET', 'POST'])
def qr_code():
    return render_template('QR_code.html',
                           upi_id=APP_INFO['upi_info']['upi_id'],
                           upi_name=APP_INFO['upi_info']['upi_name'],
                           qr_image=False)


@app.route('/generate_qr', methods=['GET', 'POST'])
def generate_qr():
    if request.method == 'POST':
        amount = request.form.get('amount')
        upi_id = request.form.get('upi_id') or APP_INFO['business']['upi_id']
        upi_name = request.form.get('upi_name') or APP_INFO['business']['upi_name']
    else:
        amount = request.args.get('amount')
        upi_id = request.args.get('upi_id') or APP_INFO['business']['upi_id']
        upi_name = request.args.get('upi_name') or APP_INFO['business']['upi_name']

    company_name = APP_INFO['business']['name']

    api_url = f"{request.host_url.rstrip('/')}/api/generate_upi_qr"
    params = {"upi_id": upi_id, "amount": amount, "company_name": company_name}

    try:
        resp = requests.get(api_url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            qr_svg_base64 = data.get('qr_svg_base64')
            upi_url = data.get('upi_url')
        else:
            qr_svg_base64 = None
            upi_url = None
    except Exception as e:
        print(f"[ERROR] failed to fetch QR: {e}")
        qr_svg_base64 = None
        upi_url = None

    qr_details = {
        'upi_id': upi_id,
        'company_name': company_name,
        'amount': amount
    }

    return render_template(
        'qr_display.html',
        upi_id=upi_id,
        qr_image=True,
        amount=amount,
        upi_name=upi_name,
        qr_code=qr_svg_base64,
        upi_url=upi_url,
        business_name=APP_INFO['business']['name'],
        amount_to_words=amount_to_words(amount)
    )


def load_supabase_config():
    try:
        url = APP_INFO['supabase']['url']
        key = APP_INFO['supabase']['key']
        last_updated = APP_INFO['supabase']['last_uploaded']
        return url, key, last_updated
    except Exception as e:
        print(f"Could not load supabase config: {e}")
        return None, None, None


def _update_supabase_last_uploaded(timestamp: str) -> None:
    info_path = ensure_info_json()
    try:
        with open(info_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        payload = {"data": {}}

    payload.setdefault("data", {})
    supabase_info = dict(payload["data"].get("supabase", {}))
    supabase_info["last_uploaded"] = timestamp
    payload["data"]["supabase"] = supabase_info

    try:
        with open(info_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
    except Exception as exc:
        print(f"[warn] Failed to update Supabase sync metadata: {exc}")
        return

    refresh_info_json()


def _update_supabase_last_incremental(timestamp: str) -> None:
    info_path = ensure_info_json()
    try:
        with open(info_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        payload = {"data": {}}

    payload.setdefault("data", {})
    supabase_info = dict(payload["data"].get("supabase", {}))
    supabase_info["last_incremental_uploaded"] = timestamp
    payload["data"]["supabase"] = supabase_info

    try:
        with open(info_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
    except Exception as exc:
        print(f"[warn] Failed to update Supabase incremental metadata: {exc}")
        return

    refresh_info_json()


def _resolve_external_backup_dir() -> Optional[Path]:
    """Return configured external backup directory, or None if unset."""
    location = (APP_INFO.get('file_location') or '').strip()
    if not location:
        return None
    try:
        return Path(location).expanduser()
    except Exception as exc:
        print(f"[warn] Invalid file_location '{location}': {exc}")
        return None


def _prune_backup_dir(directory: Path) -> None:
    """Keep only the newest BACKUP_RETENTION backup files in directory."""
    try:
        backups = sorted(
            directory.glob(f"{DATABASE_FILENAME}.*.bak"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception as exc:
        print(f"[warn] Failed to enumerate external backups in {directory}: {exc}")
        return

    for old_backup in backups[BACKUP_RETENTION:]:
        try:
            old_backup.unlink()
        except Exception as exc:
            print(f"[warn] Failed to prune external backup {old_backup}: {exc}")


def _copy_backup_to_external(backup_source: Optional[Path] = None) -> Optional[Path]:
    """Copy the DB (or provided backup file) to configured external location."""
    destination_dir = _resolve_external_backup_dir()
    if not destination_dir:
        return None

    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"[warn] Unable to prepare external backup directory {destination_dir}: {exc}")
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    source_path = backup_source if backup_source and backup_source.exists() else DB_PATH
    if backup_source and backup_source.exists() and backup_source.suffix == '.bak':
        target_name = backup_source.name
    else:
        target_name = f"{DATABASE_FILENAME}.{timestamp}.bak"

    target_path = destination_dir / target_name

    try:
        shutil.copy2(source_path, target_path)
    except Exception as exc:
        print(f"[warn] Failed to copy backup to {target_path}: {exc}")
        return None

    _prune_backup_dir(destination_dir)
    return target_path


def _create_db_backup() -> Path | None:
    backup_dir = DATA_DIR / BACKUP_DIRNAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{DATABASE_FILENAME}.{timestamp}.bak"
    try:
        shutil.copy2(DB_PATH, backup_path)
    except Exception as exc:
        print(f"[warn] Failed to create DB backup: {exc}")
        return None

    try:
        backups = sorted(backup_dir.glob(f"{DATABASE_FILENAME}.*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old_backup in backups[BACKUP_RETENTION:]:
            try:
                old_backup.unlink()
            except Exception as cleanup_exc:
                print(f"[warn] Failed to prune old backup {old_backup}: {cleanup_exc}")
    except Exception as exc:
        print(f"[warn] Failed to prune backups: {exc}")

    external_path = _copy_backup_to_external(backup_path)
    if external_path:
        print(f"[info] External backup saved to {external_path}")

    return backup_path


def _format_sync_timestamp(raw_value):
    if not raw_value:
        return "Never"
    try:
        parsed = parser.parse(str(raw_value))
    except Exception:
        return str(raw_value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_dt = parsed.astimezone(tz.tzlocal())
    date_part = local_dt.strftime("%d %b %Y")
    time_part = local_dt.strftime("%I:%M %p").lstrip('0')
    return f"{date_part} · {time_part}"


def _latest_backup_path() -> Path | None:
    backup_dir = DATA_DIR / BACKUP_DIRNAME
    if not backup_dir.exists():
        return None
    try:
        backups = sorted(
            backup_dir.glob(f"{DATABASE_FILENAME}.*.bak"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
    except Exception as exc:
        print(f"[warn] Failed to inspect backups: {exc}")
        return None
    return backups[0] if backups else None


def _ensure_recent_backup_on_shutdown() -> None:
    try:
        last_backup = _latest_backup_path()
        if last_backup is None:
            created = _create_db_backup()
            if created:
                print(f"[info] Shutdown backup created (no prior backups): {created}")
            return

        now_utc = datetime.now(timezone.utc)
        last_backup_time = datetime.fromtimestamp(last_backup.stat().st_mtime, tz=timezone.utc)
        age = now_utc - last_backup_time
        if age > timedelta(days=BACKUP_MAX_AGE_DAYS):
            created = _create_db_backup()
            if created:
                print(f"[info] Shutdown backup created (stale backup): {created}")
    except Exception as exc:
        print(f"[warn] Backup-on-shutdown failed: {exc}")


atexit.register(_ensure_recent_backup_on_shutdown)


def _check_supabase_connectivity(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    health_url = f"{url.rstrip('/')}/auth/v1/health"
    try:
        response = requests.get(health_url, timeout=timeout)
    except requests.RequestException as exc:
        return False, str(exc)

    if response.status_code >= 500:
        return False, f"Supabase health check failed with status {response.status_code}"

    return True, ""


@app.post('/supabase_sync_all')
def supabase_sync_all():
    url, key, _ = load_supabase_config()
    if not url or not key:
        flash('Supabase credentials are missing. Please update Account Settings.', 'danger')
        return redirect(url_for('more'))

    reachable, error_message = _check_supabase_connectivity(url)
    if not reachable:
        flash('Cloud sync unavailable right now — check your internet connection and try again.', 'warning')
        return redirect(url_for('more'))

    backup_path = _create_db_backup()

    if backup_path:
        print(f"[info] Created database backup at {backup_path}")

    try:
        result = upload_full_database(url, key)
    except SupabaseUploadError as exc:
        skipped = ', '.join(exc.skipped_tables) if exc.skipped_tables else 'none'
        detail = f" Reason: {exc.detail}" if exc.detail else ''
        flash(
            (
                f"Supabase rejected {exc.failed_count} records in '{exc.failed_table}'. "
                f"Upload stopped before tables: {skipped}.{detail}"
            ),
            'danger'
        )
        return redirect(url_for('more'))
    except Exception as exc:
        flash(f'Failed to sync with Supabase: {exc}', 'danger')
        return redirect(url_for('more'))

    timestamp = datetime.now(timezone.utc).isoformat()
    _update_supabase_last_uploaded(timestamp)
    flash(f'Successfully uploaded {result.uploaded} records to Supabase.', 'success')

    return redirect(url_for('more'))


@app.post('/backup/local_copy')
def create_local_backup_copy():
    refresh_info_json()
    destination = _resolve_external_backup_dir()
    if not destination:
        flash('Set a backup folder in Account Settings before creating local copies.', 'warning')
        return redirect(url_for('more'))

    backup_path = _copy_backup_to_external()
    if backup_path:
        flash(f'Backup copied to {backup_path}', 'success')
    else:
        flash('Unable to copy database to the configured folder. Check permissions and path.', 'danger')
    return redirect(url_for('more'))


@app.post('/backup/snapshot')
def create_backup_snapshot():
    backup_path = _create_db_backup()
    if backup_path:
        flash(f'Backup snapshot created at {backup_path}', 'success')
    else:
        flash('Unable to create backup snapshot. Check disk space and permissions.', 'danger')
    return redirect(url_for('more'))


@app.post('/supabase_sync_incremental')
def supabase_sync_incremental():
    url, key, _ = load_supabase_config()
    if not url or not key:
        return jsonify({
            "status": "error",
            "message": "Supabase credentials are missing. Please update Account Settings."
        }), 400

    reachable, error_message = _check_supabase_connectivity(url)
    if not reachable:
        return jsonify({
            "status": "error",
            "message": "Looks like the internet is down. Please reconnect and try again."
        }), 503

    try:
        result = upload_to_supabase(url, key)
    except Exception as exc:
        return jsonify({
            "status": "error",
            "message": f"Failed to upload incremental data: {exc}"
        }), 500

    db_result = result["db"]
    analytics_result = result["analytics"]
    archived = result["archived"]

    payload = {
        "status": "ok",
        "db_uploaded": db_result.uploaded,
        "db_failed": db_result.failed,
        "analytics_uploaded": analytics_result.uploaded,
        "analytics_failed": analytics_result.failed,
        "archived": archived,
    }

    if db_result.failed == 0 and analytics_result.failed == 0:
        timestamp = datetime.now(timezone.utc).isoformat()
        _update_supabase_last_incremental(timestamp)
        payload["message"] = (
            f"Uploaded {db_result.uploaded} changes"
            f" and {analytics_result.uploaded} analytics events."
        )
        payload["last_uploaded"] = _format_sync_timestamp(timestamp)
    else:
        payload["status"] = "partial"
        payload["message"] = (
            "Incremental sync finished with errors. "
            "Check logs/failed for details."
        )
        supabase_meta = APP_INFO.get('supabase', {})
        previous = supabase_meta.get('last_incremental_uploaded') or supabase_meta.get('last_uploaded')
        payload["last_uploaded"] = _format_sync_timestamp(previous)

    return jsonify(payload)


if __name__ == '__main__':
    app.run(debug=True)
