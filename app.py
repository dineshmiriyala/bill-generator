from logging import exception

from flask import Flask, render_template, render_template_string, request, Response, jsonify, redirect, url_for
from datetime import datetime, timedelta, timezone

from pandas.core.computation import scope
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from pdf import generate_invoice_pdf
from flask_migrate import Migrate
from db.models import *
from sqlalchemy.orm import joinedload
import os
import csv, io
from urllib.parse import urlparse
from collections import defaultdict



basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(basedir, 'db', 'app.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
migrate = Migrate(app, db)

# Helpers for statement engine
def _parse_date(date_str):
    """Parse 'YYYY-MM-DD' into date or return None."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except Exception:
        return None

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


# Home Route
@app.route('/')
def home():
    return render_template('home.html')

#customers page (temperory placeholder)
@app.route('/create_customers', methods=['GET', 'POST'])
def add_customers():
    # this is the functon to create a new customer
    # refer to add_customer.html to see frontend
    if request.method == 'POST':
        action = (request.form.get('action') or 'save').lower()  # 'save' or 'create_and_bill'
        phone = (request.form.get('phone') or '').strip()
        name = (request.form.get('name') or '').strip()
        company = (request.form.get('company') or '').strip()
        email = (request.form.get('email') or '').strip()
        gst = (request.form.get('gst') or '').strip()
        address = (request.form.get('address') or '').strip()
        businessType = (request.form.get('businessType') or '').strip()

        # Basic validation
        if not phone or not name:
            return render_template('add_customer.html', success=False, duplicate=False, error='Name and phone are required.')

        # Try to find existing by phone (unique)
        existing = customer.query.filter_by(phone=phone).first()

        if action == 'create_and_bill':
            # Use existing if present; else create then proceed to bill
            if existing:
                sel = existing
            else:
                sel = customer(
                    name=name,
                    company=company,
                    phone=phone,
                    email=email,
                    gst=gst,
                    address=address,
                    businessType=businessType
                )
                db.session.add(sel)
                db.session.commit()
            # Open the create bill page preloaded
            return render_template('create_bill.html', customer=sel, inventory=item.query.all())

        # Normal save flow
        if existing:
            # Show duplicate message, preserve form values (template already binds request.form)
            return render_template('add_customer.html', duplicate=True)

        new_customer = customer(
            name=name,
            company=company,
            phone=phone,
            email=email,
            gst=gst,
            address=address,
            businessType=businessType
        )
        db.session.add(new_customer)
        db.session.commit()

        return render_template('add_customer.html', success=True)

    return render_template('add_customer.html')



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

        return render_template('add_inventory.html', success=True)

    return render_template('add_inventory.html')

@app.route('/select_customer', methods=['GET', 'POST'])
def select_customer():
    if request.method == 'POST':
        # User clicked Select on a customer row; the form sends phone
        phone = request.form.get('customer')
        sel = customer.query.filter_by(phone=phone).first_or_404()
        return render_template('create_bill.html', customer=sel, inventory=item.query.all())

    # GET: either search or show recent
    q = (request.args.get('q') or '').strip()
    if q:
        like = f"%{q}%"
        customers = (customer.query
                     .filter((customer.phone.ilike(like)) |
                             (customer.name.ilike(like))  |
                             (customer.company.ilike(like)))
                     .order_by(customer.id.desc())
                     .limit(100)
                     .all())
    else:
        customers = (customer.query
                     .order_by(customer.id.desc())
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

@app.route('/statements', methods=['GET'])
def statements():
    """HTML/CSV Statement for month/year/custom with optional phone filter.
    Query params:
      - scope: 'month' | 'year' | 'custom' (default: current year when absent)
      - year, month (when scope requires it)
      - start, end in YYYY-MM-DD (custom)
      - phone (optional exact match)
      - format: 'html' (default) or 'csv'
    """
    scope = (request.args.get('scope') or '').lower()
    fmt = (request.args.get('format') or 'html').lower()
    phone = request.args.get('phone')

    # Default: if no scope supplied, go to current year
    if not scope:
        return redirect(url_for('statements_blank'))

    # Resolve date range
    today = datetime.now(timezone.utc).date()
    start_dt = end_dt = None
    try:
        if scope == 'year':
            year = int(request.args.get('year') or today.year)
            start_dt = datetime(year, 1, 1, tzinfo=timezone.utc)
            end_dt   = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
        elif scope == 'month':
            year = int(request.args.get('year') or today.year)
            month = int(request.args.get('month') or today.month)
            start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
            if month == 12:
                end_dt = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
            else:
                end_dt = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
        elif scope == 'custom':
            start = request.args.get('start')
            end   = request.args.get('end')
            if not (start and end):
                # Render friendly page instead of 400
                return render_template(
                    'statement.html',
                    start_date=None,
                    end_date=None,
                    total_invoices=0,
                    total_amount=0,
                    phone=phone or '',
                    per_customer={},
                    invs=[],
                    scope='custom',
                    error='Please choose a date range to view custom statements.'
                )
            start_dt = datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            # inclusive end-of-day
            end_dt = datetime.strptime(end, '%Y-%m-%d').replace(tzinfo=timezone.utc) + timedelta(days=1) - timedelta(seconds=1)
        else:
            # Unknown scope -> default to current year
            return redirect(url_for('statements', scope='year', year=today.year))
    except Exception:
        # On any parsing issue, fall back to current year
        return redirect(url_for('statements', scope='year', year=today.year))

    # Base query: exclude soft-deleted; within range
    q = (invoice.query
         .options(joinedload(invoice.customer))
         .filter(invoice.isDeleted == False,
                 invoice.createdAt >= start_dt,
                 invoice.createdAt <= end_dt))

    if phone:
        q = q.join(customer, invoice.customerId == customer.id).filter(customer.phone == phone)

    invs = q.order_by(invoice.createdAt.desc()).all()

    # Aggregations
    total_invoices = len(invs)
    total_amount = sum(float(inv.totalAmount or 0) for inv in invs)

    per_customer = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for inv in invs:
        cust = inv.customer
        label = f"{cust.name} ({cust.phone})" if cust else 'Unknown'
        per_customer[label]["count"] += 1
        per_customer[label]["amount"] += float(inv.totalAmount or 0)

    if fmt == 'csv':
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Invoice No", "Date", "Customer", "Phone", "Total Amount"])
        for inv in invs:
            cust = inv.customer
            writer.writerow([
                inv.invoiceId,
                inv.createdAt.strftime('%Y-%m-%d'),
                cust.name if cust else 'Unknown',
                cust.phone if cust else '',
                f"{float(inv.totalAmount or 0):.2f}"
            ])
        writer.writerow([])
        writer.writerow(["TOTAL INVOICES", total_invoices])
        writer.writerow(["TOTAL AMOUNT", f"{total_amount:.2f}"])
        # simple filename
        return Response(buf.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment; filename=statement.csv'})

    return render_template(
        'statement.html',
        start_date=start_dt.date(),
        end_date=end_dt.date(),
        total_invoices=total_invoices,
        total_amount=round(total_amount, 2),
        per_customer=per_customer,
        invs=invs,
        scope=scope,
        phone=phone,
        request=request,
    )

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
        end_date = datetime(year, 12, 31).date() if month == 12 else (datetime(year, month + 1, 1).date() - timedelta(days=1))
    else:
        start_date = _parse_date(request.args.get('start'))
        end_date = _parse_date(request.args.get('end'))
        if not (start_date and end_date):
            return jsonify({"error": "Provide start and end in YYYY-MM-DD for custom scope"}), 400

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    q = invoice.query.options(joinedload(invoice.customer)).filter(
        invoice.createdAt >= start_dt,
        invoice.createdAt <= end_dt
    )
    if phone:
        q = q.join(customer, invoice.customerId == customer.id).filter(customer.phone == phone)
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
        end_date = datetime(year, 12, 31).date() if month == 12 else (datetime(year, month + 1, 1).date() - timedelta(days=1))
    else:
        start_date = _parse_date(request.args.get('start'))
        end_date = _parse_date(request.args.get('end'))
        if not (start_date and end_date):
            return jsonify({"error": "Provide start and end in YYYY-MM-DD for custom scope"}), 400

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    q = invoice.query.options(joinedload(invoice.customer)).filter(
        invoice.createdAt >= start_dt,
        invoice.createdAt <= end_dt
    )
    if phone:
        q = q.join(customer, invoice.customerId == customer.id).filter(customer.phone == phone)

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
        start_date = None,
        end_date = None,
        total_invoices = 0,
        total_amount = 0,
        phone = None,
        per_customer = {},
        invs = [],
        scope = 'custom',
    )

@app.route('/create-bill', methods = ['GET', 'POST'])
def start_bill():

    if request.method == 'POST':
        if 'description[]' in request.form:
            selected_phone = request.form.get('customer_phone')
            selected_customer = customer.query.filter_by(phone=selected_phone).first()

            descriptions = request.form.getlist('description[]')
            quantities = request.form.getlist('quantity[]')
            rates = request.form.getlist('rate[]')
            dc_numbers = request.form.getlist('dc_no[]')  # present only if toggle is on

            total = 0
            item_rows = []
            for i in range(len(descriptions)):
                desc = descriptions[i]
                qty = int(quantities[i]) if i < len(quantities) and quantities[i] else 0
                rate = float(rates[i]) if i < len(rates) and rates[i] else 0.0
                dc_val = (dc_numbers[i].strip() if i < len(dc_numbers) and dc_numbers[i] else '')
                line_total = qty * rate
                total += line_total
                item_rows.append([desc, qty, rate, line_total, dc_val])

            #creating invoice entry
            new_invoice = invoice(
                customerId = selected_customer.id,
                createdAt = datetime.now(timezone.utc),
                totalAmount = round(total, 2),
                pdfPath = "", # to be filled after filename is known
                invoiceId = "" # temporary placeholder
            )

            db.session.add(new_invoice)
            db.session.commit()

            #generating PDF id and PDF name
            inv_name = f"SLP-{datetime.now().strftime('%d%m%y')}-{str(new_invoice.id).zfill(5)}"
            pdf_filename = f"{inv_name}.pdf"
            pdf_path = os.path.join("static/pdfs", pdf_filename)

            new_invoice.invoiceId = inv_name
            new_invoice.pdfPath = pdf_path
            db.session.commit()

            # add invoice Items
            for desc, qty, rate, line_total, dc_val in item_rows:
                matched_item = item.query.filter_by(name=desc).first()
                if matched_item:
                    item_id = matched_item.id
                else:
                    new_item = item(
                        name=desc,  # place holder for future
                        unitPrice=rate,
                        quantity=0,
                        taxPercentage=0
                    )
                    db.session.add(new_item)
                    db.session.commit()
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

            return render_template(
                'create_bill.html',
                customer=selected_customer,
                inventory=item.query.all(),
                success=True,
                filename=pdf_filename,
                descriptions=descriptions,
                quantities=quantities,
                rates=rates,
                dc_numbers=dc_numbers,
                dcno=any(x.strip() for x in dc_numbers),
                total=total
            )

        else:
            selected_phone = request.form.get("customer")
            selected_customer = customer.query.filter_by(phone = selected_phone).first()
            return render_template('create_bill.html', customer = selected_customer, inventory=item.query.all())

    return render_template('select_customer.html')



@app.route('/view_customers', methods=['GET', 'POST'])
def view_customers():
    # If user clicked "Create Bill" on a row, the form posts the customer's phone
    if request.method == 'POST':
        phone = request.form.get('customer')
        sel = customer.query.filter_by(phone=phone).first_or_404()
        return render_template('create_bill.html', customer=sel, inventory=item.query.all())

    # GET: current behavior (optional search)
    query = (request.args.get('q') or '').lower()
    customers = customer.query.all()

    if query:
        customers = [
            c for c in customers
            if query in (c.name or '').lower() or query in (c.phone or '') or query in (c.company or '').lower()
        ]

    return render_template('view_customers.html', customers=customers)

@app.route('/view_bills')
def view_bills():
    query = (request.args.get('q') or '').lower()
    phone = request.args.get('phone')
    start_date = request.args.get('start_date')
    end_date   = request.args.get('end_date')

    q = (invoice.query.options(joinedload(invoice.customer))
         .filter(invoice.isDeleted == False))

    # sorting controls
    sort_key = (request.args.get('sort') or 'date').lower()
    sort_dir = (request.args.get('dir') or 'desc').lower()

    def order(col):
        return col.desc() if sort_dir == 'desc' else col.asc()

    if sort_key == 'total':
        q = q.order_by(order(invoice.totalAmount))
    elif sort_key == 'invoice':
        q = q.order_by(order(invoice.invoiceId))
    elif sort_key == 'customer':
        q = (q.join(customer, invoice.customerId == customer.id)
             .order_by(order(customer.name)))
    else:
        # default: sort by date
        q = q.order_by(order(invoice.createdAt))

    # Apply date range if provided (YYYY-MM-DD)
    try:
        if start_date and end_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt   = datetime.strptime(end_date,   '%Y-%m-%d') + timedelta(days=1)  # inclusive
            q = q.filter(invoice.createdAt >= start_dt, invoice.createdAt < end_dt)
    except Exception:
        pass

    invoices = q.all()

    results = []
    for inv in invoices:
        cust = inv.customer
        results.append({
            "invoice_no": inv.invoiceId,
            "date": inv.createdAt.strftime('%m/%d/%Y'),
            "customer_name": cust.name if cust else 'Unknown',
            "phone": cust.phone if cust else '',
            "total": f"{inv.totalAmount: ,.2f}",
            "filename": f"{inv.invoiceId}.pdf",
        })

    bills = results
    if phone:
        bills = [b for b in bills if b['phone'] == phone]
    elif query:
        bills = [b for b in bills if query in b['customer_name'].lower()
                                   or query in b.get('phone', '')
                                   or query in b['invoice_no']]

    return render_template('view_bills.html', bills=bills)

@app.route('/view-bill/<invoicenumber>')
def view_bill_locked(invoicenumber):
    # load invoice and related data
    current_invoice = invoice.query.filter_by(invoiceId=invoicenumber, isDeleted=False).first_or_404()
    current_customer = customer.query.get(current_invoice.customerId)
    line_items = invoiceItem.query.filter_by(invoiceId = current_invoice.id).all()

    # build row wise lists for the template
    descriptions, quantities, rates, dc_numbers = [], [], [], []

    total = 0.0
    for li in line_items:
        itm = item.query.get(li.itemId)
        descriptions.append(itm.name if itm else 'Unknown')
        quantities.append(li.quantity)
        rates.append(li.rate)
        dc_numbers.append(li.dcNo or '')
        total += (li.quantity or 0) * (li.rate or 0)

    # Determine whether to show DC column
    dcno = any((x or '').strip() for x in dc_numbers)

    return render_template(
        'view_bill_locked.html',
        customer=current_customer,
        descriptions=descriptions,
        quantities=quantities,
        rates=rates,
        dc_numbers=dc_numbers,
        dcno=dcno,
        total=round(total, 2),
        invoice_no=current_invoice.invoiceId
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
    crore = num // 10000000; num %= 10000000
    lakh = num // 100000; num %= 100000
    thousand = num // 1000; num %= 1000
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
    current_invoice = invoice.query.filter_by(invoiceId = invoicenumber, isDeleted=False).first_or_404()
    if not current_invoice:
        return f"No invoice found for {invoicenumber}"

    current_customer = customer.query.get(current_invoice.customerId)
    items = invoiceItem.query.filter_by(invoiceId = current_invoice.id).all()
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
    dc_numbers = [i.dcNo or '' for i in items]
    dcno = any(bool((x or '').strip()) for x in dc_numbers)
    return render_template('bill_preview.html',
                           invoice=current_invoice,
                           customer=current_customer,
                           items=item_data, dcno=dcno,
                           dc_numbers=dc_numbers,
                           total_in_words = amount_to_words(current_invoice.totalAmount))


@app.route('/edit-bill/<invoicenumber>')
def edit_bill(invoicenumber):
    # fetch invoice and related data
    current_invoice = invoice.query.filter_by(invoiceId=invoicenumber).first_or_404()
    current_customer = customer.query.get(current_invoice.customerId)
    line_items = invoiceItem.query.filter_by(invoiceId=current_invoice.id).all()

    # Build lists for template
    descriptions, quantities, rates, dc_numbers = [], [], [], []
    total = 0.0
    for li in line_items:
        itm = item.query.get(li.itemId)
        descriptions.append(itm.name if itm else 'Unknown')
        quantities.append(li.quantity)
        rates.append(li.rate)
        dc_numbers.append(li.dcNo or '')
        total += (li.quantity or 0) * (li.rate or 0)

    dcno = any((x or '').strip() for x in dc_numbers)

    prev_invoice_no = current_invoice.invoiceId
    try:
        prev_created_at = current_invoice.createdAt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        prev_created_at = str(current_invoice.createdAt)

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
        invoice_no=current_invoice.invoiceId,
        edit_mode=True,  # flag to distinguish editing vs new bill
        prev_invoice_no=prev_invoice_no,
        prev_created_at=prev_created_at
    )


@app.route('/delete-bill/<invoicenumber>', methods = ['POST'])
def delete_bill(invoicenumber):
    inv = invoice.query.filter_by(invoiceId=invoicenumber, isDeleted=False).first_or_404()
    inv.isDeleted = True
    inv.deletedAt = datetime.now(timezone.utc)
    db.session.commit()

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
    quantities   = request.form.getlist('quantity[]')
    rates        = request.form.getlist('rate[]')
    dc_numbers   = request.form.getlist('dc_no[]')  # may be empty if toggle off

    # 3) Normalize rows + recompute totals
    rows = []
    total = 0.0
    for i in range(len(descriptions)):
        desc = (descriptions[i] or '').strip()
        if not desc:
            continue  # skip empty rows

        qty  = int(quantities[i]) if i < len(quantities) and quantities[i] else 0
        rate = float(rates[i])    if i < len(rates)      and rates[i]      else 0.0
        dc   = (dc_numbers[i].strip() if i < len(dc_numbers) and dc_numbers[i] else None)

        line_total = qty * rate
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
    current_invoice.totalAmount = round(total, 2)
    # If you added this column:
    # from datetime import datetime
    # current_invoice.updatedAt = datetime.utcnow()

    db.session.commit()

    # 6) Re-render edit page with success banner and correct flags
    dcno = any(bool((x or '').strip()) for x in dc_numbers)

    return render_template(
        'create_bill.html',
        customer=current_customer,
        inventory=item.query.all(),
        success=True,                 # triggers "Bill updated successfully!"
        descriptions=[r[0] for r in rows],
        quantities=[r[1] for r in rows],
        rates=[r[2] for r in rows],
        dc_numbers=[(r[3] or '') for r in rows],
        dcno=dcno,
        total=round(total, 2),
        invoice_no=current_invoice.invoiceId,
        edit_mode=True
    )

@app.route('/bill_preview/latest')
def latest_bill_preview():

    current_invoice = invoice.query.order_by(invoice.id.desc()).first()
    if not current_invoice:
        return "No invoice found"

    current_customer = customer.query.get(current_invoice.customerId)
    items = invoiceItem.query.filter_by(invoiceId = current_invoice.id).all()
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
    dc_numbers = [i.dcNo or '' for i in items]
    dcno = any(bool((x or '').strip()) for x in dc_numbers)
    return render_template('bill_preview.html', invoice=current_invoice, customer=current_customer, items=item_data, dcno=dcno, dc_numbers=dc_numbers)



@app.route('/downlaod-pdf/<int:invoice_id>')
def downlaod_pdf(invoice_id):
    current_invoice = invoice.query.get_or_404(invoice_id)
    current_customer = customer.query.get(current_invoice.customerId)
    items = invoiceItem.query.filter_by(invoiceId = current_invoice.id).all()
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
    dc_numbers = [i.dcNo or '' for i in items]
    dcno = any(bool((x or '').strip()) for x in dc_numbers)
    html_content = render_template(
        'bill_preview.html',
        invoice=current_invoice,
        customer=current_customer,
        items=item_data,
        dcno=dcno,
        dc_numbers=dc_numbers
    )

    filename = f"{current_invoice.invoiceId}.pdf"
    filepath = os.path.join(app.root_path, 'static/pdf', filename)
    HTML(string = html_content, base_url = request.base.url).write_pdf(filepath)

    return f"PDF Generated Successfully! <a href = '/static/pdfs/{filename}' target = '_blank'>View PDF</a>"
@app.route('/generate-pdf')
def generate_pdf(invoice_id, customer, items, total):
    generate_invoice_pdf()

    return f"PDF generated successfully! <a href = '/static/pdfs/generated_invoice.pdf' target='_blank'>View PDF</a>"


app.jinja_env.globals.update(zip=zip)

if __name__ == '__main__':
    app.run(debug=True)