from flask import Flask, render_template, render_template_string, request, Response, jsonify, redirect, url_for, flash
from analytics import get_sales_trends, get_top_customers, get_customer_retention, get_day_wise_billing
from datetime import datetime, timedelta, timezone
from flask_migrate import Migrate
from db.models import *
from sqlalchemy.orm import joinedload
import os
import csv, io
from urllib.parse import urlparse
from collections import defaultdict
import uuid
from sqlalchemy import func, or_
from sqlalchemy import inspect
from flask import session
import os
from pathlib import Path
import os, sys, shutil
from pathlib import Path
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from migration import migrate_db
from flask import send_file
import io
import json
from api import api_bp

def _format_customer_id(n: int) -> str:
    return f"ID-{n:06d}"


# ---- Owner / Business profile (edit these to your real values) ----
USER_PROFILE = {
    "company": "Sri Lakshmi Offset Printers",
    "name": "Sri Lakshmi Offset Printers",
    "tagline": "Quality since 1973",
    "address": "Pamarru, Krishna Dist - 521157",
    "phone": "9848992207",
    "email": "haripress@gmail.com",
    "gst": "37AVEPM5991R3ZG",
    "pan": None,
    "businessType": "Composition",
    "established": "1973",
    "website": None,  # e.g., "https://example.com"
    "billType": "Bill of Supply",
    "isComposition": True,
    "showRemarks": False,
    "logo_path": "img/brand-wordmark.svg",  # under /static

    "bank": {
        "accountName": "Sri Lakshmi Offset Printers",
        "bankName": "State Bank of India",
        "branch": "Pamarru",
        "accountNumber": "38588014977",
        "ifsc": "SBIN0002776",
        "PhonePe/GPay": "9848992207",
    },
}
# --- top of app.py: imports & app/db config ---


app = Flask(__name__)
basedir = Path(__file__).parent.resolve()
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'super-secret')
app.register_blueprint(api_bp)


def _desktop_data_dir(app_name: str) -> Path:
    if os.name == "nt":
        return Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / app_name
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    else:
        return Path.home() / ".local" / "share" / app_name


# Determine DB path before calling migrate_db
if os.getenv("BG_DESKTOP") == "1":
    db_file = _desktop_data_dir("SLO BILL") / "app.db"
else:
    db_file = basedir / "db" / "app.db"

migrate_db(db_file.as_posix())  # <- Pass resolved DB path

APP_NAME = "SLO BILL"
is_desktop = os.getenv("BG_DESKTOP") == "1"

if is_desktop:
    data_dir = _desktop_data_dir(APP_NAME)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "app.db"
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_file.as_posix()}"
else:
    db_file = basedir / "db" / "app.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_file.as_posix()}"

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ✅ Reuse the ONE db from your models module
from db.models import db, customer, invoice, invoiceItem, item  # import your models & shared db

# Attach to this Flask app
db.init_app(app)
migrate = Migrate(app, db)

# add at top with other imports
from sqlalchemy import inspect
from decimal import Decimal, ROUND_HALF_UP

def rounding_to_nearest_zero(amount):
    """Rounding number to nearest zero"""
    try:
        d = Decimal(str(amount))
    except Exception:
        d = Decimal('0')
    tens = (d / Decimal('10')).quantize(Decimal('1'), rounding = ROUND_HALF_UP)
    return float(tens * Decimal('10'))

def _ensure_db_initialized():
    """
    Ensure database schema exists.
    - If DB file missing: create schema (or copy seed if present + desktop).
    - If DB file exists but has no tables: create schema.
    """
    seed_db = basedir / "db" / "app.db"  # optional seed; ok if missing

    with app.app_context():
        # create file if missing (and optionally copy seed on desktop)
        if not db_file.exists():
            try:
                if seed_db.exists() and is_desktop:
                    shutil.copy2(seed_db, db_file)
                    print("[info] Copied seed DB to desktop data dir.")
                else:
                    # touch file so engine can open it cleanly
                    db_file.parent.mkdir(parents=True, exist_ok=True)
                    db_file.touch(exist_ok=True)
                    print("[info] Created empty DB file.")
            except Exception as e:
                print(f"[warn] could not prepare DB file: {e}")

        # check whether tables exist
        insp = inspect(db.engine)
        tables = set(insp.get_table_names())

        required = {"customer", "invoice", "invoice_item", "item"}
        # adjust names if your table names differ

        if not required.issubset(tables):
            print("[info] Creating/migrating schema via create_all()…")
            db.create_all()


# ✅ Call this AFTER importing models, so metadata is populated
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
    return render_template(
        'more.html'
    )

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


@app.route("/about_user")
def about_user():
    """Owner/Business profile + optional customer snapshot, with better search.
       Query:
         - q: free text (company/name/phone)
         - customer_id: exact id
         - phone: substring (fallback)
    """
    prof = dict(USER_PROFILE)

    # Invoices query (exclude soft-deleted if exists)
    try:
        q_inv = db.session.query(invoice).filter(invoice.isDeleted == False)
    except Exception:
        q_inv = db.session.query(invoice)

    # Basic stats
    prof["invoiceCount"] = q_inv.count()
    prof["customerCount"] = db.session.query(func.count(customer.id)).scalar() or 0

    # Activity (timestamps + invoice numbers)
    first_inv = q_inv.order_by(invoice.createdAt.asc()).first()
    last_inv = q_inv.order_by(invoice.createdAt.desc()).first()
    prof["createdAt"] = getattr(first_inv, "createdAt", None)
    prof["updatedAt"] = getattr(last_inv, "createdAt", None)
    prof["firstInvoiceNo"] = getattr(first_inv, "invoiceId", None)
    prof["lastInvoiceNo"] = getattr(last_inv, "invoiceId", None)

    # Total billed
    try:
        total_billed = db.session.query(
            func.coalesce(func.sum(invoice.totalAmount), 0)
        ).filter(invoice.isDeleted == False).scalar() or 0
    except Exception:
        total_billed = db.session.query(
            func.coalesce(func.sum(invoice.totalAmount), 0)
        ).scalar() or 0
    prof["totalBilled"] = f"INR: {float(total_billed):,.2f}"

    # ---- Improved customer selection logic ----
    cust = None
    matches = []  # optional list of matches to render in template

    # Priority 1: ?customer_id=...
    cid = (request.args.get('customer_id') or '').strip()
    if cid.isdigit():
        cust = (customer.query
                .filter(customer.isDeleted == False, customer.id == int(cid))
                .first())

    # Priority 2: ?q=...  (search company/name/phone)
    if not cust:
        qtext = (request.args.get('q') or '').strip()
        if qtext:
            like = f"%{qtext}%"
            base = customer.query.filter(customer.isDeleted == False)
            matches = (base.filter(
                or_(customer.company.ilike(like),
                    customer.name.ilike(like),
                    customer.phone.ilike(like)))
                       .order_by(customer.createdAt.desc(), customer.id.desc())
                       .limit(25)
                       .all())
            if len(matches) == 1:
                cust = matches[0]
            elif len(matches) > 0:
                # pick newest as the snapshot, but also return matches for UI
                cust = matches[0]
            else:
                flash("No customer matched your search.", "warning")

    # Priority 3: ?phone=... (legacy fallback)
    if not cust:
        cphone = (request.args.get('phone') or '').strip()
        if cphone:
            like = f"%{cphone}%"
            cust = (customer.query
                    .filter(customer.isDeleted == False, customer.phone.ilike(like))
                    .order_by(customer.id.desc())
                    .first())

    # Priority 4: latest customer
    if not cust:
        cust = (customer.query
                .filter(customer.isDeleted == False)
                .order_by(customer.id.desc())
                .first())

    latest_cust = cust
    cust_stats, cust_invs = {}, []
    if latest_cust:
        invs_q = (invoice.query
                  .filter(invoice.customerId == latest_cust.id,
                          getattr(invoice, 'isDeleted', False) == False)
                  .order_by(invoice.createdAt.desc()))
        cust_invs = invs_q.limit(10).all()

        first_inv_c = invs_q.order_by(invoice.createdAt.asc()).first()
        last_inv_c = cust_invs[0] if cust_invs else None
        total_val = db.session.query(func.coalesce(func.sum(invoice.totalAmount), 0)).filter(
            invoice.customerId == latest_cust.id,
            getattr(invoice, 'isDeleted', False) == False
        ).scalar() or 0
        cust_stats = {
            'invoiceCount': invs_q.count(),
            'firstInvoiceDate': first_inv_c.createdAt.strftime('%d %b %Y') if getattr(first_inv_c, 'createdAt',
                                                                                      None) else None,
            'lastInvoiceDate': last_inv_c.createdAt.strftime('%d %b %Y') if getattr(last_inv_c, 'createdAt',
                                                                                    None) else None,
            'totalBilled': f"INR: {float(total_val):,.2f}",
        }

    return render_template(
        'about_user.html',
        user=prof,
        latest_customer=latest_cust,
        cust_stats=cust_stats,
        cust_invs=cust_invs,
        matches=matches,  # <-- pass matches (optional)
        q=(request.args.get('q') or '').strip()
    )


# Custom Jinja filter to format dates as DD-MM-YYYY
@app.template_filter('datetimeformat')
def datetimeformat(value, format='%d-%m-%Y'):
    if not value:
        return ''
    try:
        if isinstance(value, str):
            value = datetime.strptime(value, '%Y-%m-%d')
        return value.strftime(format)
    except Exception:
        return value


@app.route('/_flash_test')
def _flash_test():
    flash('Flash works!', 'success')
    return redirect(url_for('view_customers'))


# Home Route
@app.route('/')
def home():
    session['persistent_notice'] = None
    return render_template('home.html')


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
    db.session.commit()
    # Add Alert - Not needed

    # Generate invoice Id + pdf path
    inv_name = f"SLP-{datetime.now().strftime('%d%m%y')}-{str(new_invoice.id).zfill(5)}"
    pdf_filename = f"{inv_name}.pdf"
    pdf_path = os.path.join("static/pdfs", pdf_filename)

    new_invoice.invoiceId = inv_name
    new_invoice.pdfPath = pdf_path
    db.session.commit()
    # add alerts - not needed as persistant on in place

    # Add line items
    for desc, qty, rate, line_total, dc_val in item_rows:
        matched_item = item.query.filter_by(name=desc).first()
        if matched_item:
            item_id = matched_item.id
        else:
            new_item = item(name=desc, unitPrice=rate, quantity=0, taxPercentage=0)
            db.session.add(new_item)
            db.session.commit()
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
    return redirect(url_for('view_bill_locked', invoicenumber=new_invoice.invoiceId, new_bill = 'True'))


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
    def order(col): return col.desc() if sort_dir == 'desc' else col.asc()

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
    back_to_select_customer = new_bill
    edit_bill = request.args.get('edit_bill', '').lower() in ('yes', 'true', '1')
    back_two_pages = edit_bill

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

    return render_template(
        'bill_preview.html',
        invoice=current_invoice,
        customer=current_customer,
        items=item_data,
        dcno=dcno,
        dc_numbers=dc_numbers,
        total_in_words=amount_to_words(current_invoice.totalAmount),
        sizes=current_sizes
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
        return redirect(url_for('view_bill_locked', invoicenumber=current_invoice.invoiceId, edit_bill = 'true'))

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

    # 4) Replace all existing line items with the new set
    invoiceItem.query.filter_by(invoiceId=current_invoice.id).delete()

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

    return redirect(url_for('view_bill_locked', invoicenumber=current_invoice.invoiceId, edit_bill = 'true'))


@app.route('/bill_preview/latest')
def latest_bill_preview():
    current_invoice = (invoice.query.
                       filter(invoice.isDeleted == False)
                       .order_by(invoice.id.desc()).first())
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
    return render_template('bill_preview.html',
                           invoice=current_invoice,
                           customer=current_customer,
                           items=item_data,
                           dcno=dcno,
                           dc_numbers=dc_numbers,
                           total_in_words=amount_to_words(current_invoice.totalAmount),
                           sizes=current_sizes)



# --- Common builder for sample invoice context ---

def _build_sample_invoice_context():
    # Get the most recent invoice
    recent_invoice = invoice.query.order_by(invoice.createdAt.desc()).first()

    if not recent_invoice:
        # Fallback if no invoice exists
        return {
            "invoice": type("Invoice", (), {"invoiceId": "NO_DATA", "createdAt": datetime.utcnow(), "totalAmount": 0.0})(),
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
            session['persistent_notice'] = "✅ Layout has been updated successfully!"

    elif action == "reset":
        config.reset_sizes()
        db.session.commit()
        session['persistent_notice'] = "✅ Layout has been reset to defaults!"

    return _build_sample_invoice_context()


# --- Routes ---
@app.route('/test-pre-preview', methods=['GET'])
def test_pre_preview():
    try:
        if session['persistent_notice']:
            pass  # keep notice, just no backup check
    except Exception:
        pass
    ctx = handle_layout(action="view")
    return render_template("pre-preview-bill.html", **ctx)

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




# --- /statements route (customer statements with export options) ---
@app.route('/statements', methods=['GET'])
def statements():
    """
    Render customer statements for a date range or customer, with export (HTML, CSV, PDF).
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
        # fallback: default to current month
        if not (start_date and end_date):
            start_date = today.replace(day=1)
            end_date = today

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    # Query invoices within range, eager-load customer
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

    # Compute totals and per-customer summary
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

    # Ensure per_customer is always defined as a dict (never Undefined)
    if not per_customer:
        per_customer = {}

    # Export CSV
    if export == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Invoice No", "Date", "Customer", "Company", "Phone", "Amount"])
        for inv in invs:
            cust = inv.customer
            writer.writerow([
                inv.invoiceId,
                inv.createdAt.strftime('%Y-%m-%d'),
                cust.name if cust else 'Unknown',
                cust.company if cust else '',
                cust.phone if cust else '',
                f"{inv.totalAmount:,.2f}"
            ])
        csv_val = output.getvalue()
        return Response(
            csv_val,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment;filename=statements_{start_date}_{end_date}.csv"}
        )

    # Export PDF (if PDF export is available; placeholder, as actual PDF code may differ)
    if export == "pdf":
        try:
            from flask_weasyprint import render_pdf
            # Render HTML first
            html = render_template(
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
            return render_pdf(html, download_filename=f"statements_{start_date}_{end_date}.pdf")
        except ImportError:
            return "PDF export requires flask-weasyprint", 501

    # Default: HTML view
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
    fmt = (request.args.get('format') or 'html').lower()
    start = request.args.get('start')
    end = request.args.get('end')

    today = datetime.now(timezone.utc).date()
    start_dt = datetime(today.year, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime.now(timezone.utc)

    # --- Parse date range if provided ---
    if start and end:
        try:
            start_dt = datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            end_dt = datetime.strptime(end, '%Y-%m-%d').replace(tzinfo=timezone.utc) + timedelta(days=1) - timedelta(seconds=1)
        except Exception:
            flash("Invalid date format. Expected YYYY-MM-DD.", "warning")

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
    if query:
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
    if fmt == 'csv' and query:
        buf = io.StringIO()
        writer = csv.writer(buf)

        # Header
        writer.writerow(["Sri Lakshmi Offset Printers - Customer Statement"])
        writer.writerow(["Generated On", datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        writer.writerow(["Customer/Company", query])
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
        writer.writerow(["Account Name", USER_PROFILE["bank"]["accountName"]])
        writer.writerow(["Bank", f"{USER_PROFILE['bank']['bankName']}, {USER_PROFILE['bank']['branch']}"])
        writer.writerow(["Account Number", USER_PROFILE["bank"]["accountNumber"]])
        writer.writerow(["IFSC", USER_PROFILE["bank"]["ifsc"]])
        writer.writerow(["PhonePe/GPay", USER_PROFILE["bank"]["PhonePe/GPay"]])
        writer.writerow([])

        writer.writerow(["Disclaimer", "This is a system-generated statement. No signature required."])

        safe_name = (query or "company").replace(" ", "_").replace("/", "_")
        filename = f"{safe_name}_statement_{datetime.now().strftime('%Y-%m-%d')}.csv"

        return Response(
            buf.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )

    # --- PDF Export ---
    if fmt == 'pdf' and query:
        # Use print-friendly HTML template for print preview
        return render_template(
            'statements_company_print.html',
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
            company_wise=True
        )

    # --- Build rows for HTML template ---
    inv_rows = []
    for inv in invs:
        inv_rows.append({
            "invoice_no": inv.invoiceId,
            "date": inv.createdAt.strftime('%Y-%m-%d'),
            "total": float(inv.totalAmount or 0),
        })

    customer_company = ''
    customer_phone = ''

    if invs and invs[0].customer:
        customer_company = invs[0].customer.company or ''
        customer_phone = invs[0].customer.phone or ''

    print(f"Customer Company : {customer_company}")
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
        company_wise=False
    )

if __name__ == '__main__':
    app.run(debug=True)