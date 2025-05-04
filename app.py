from logging import exception

from flask import Flask, render_template, request
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from pdf import generate_invoice_pdf
from flask_migrate import Migrate
from db.models import *
from sqlalchemy.orm import joinedload
import os




basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(basedir, 'db', 'app.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
migrate = Migrate(app, db)

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
        phone = request.form.get('phone')
        existing = customer.query.filter_by(phone = phone).first()
        if existing:
            return render_template('add_customer.html', duplicate = True)

        new_customer = customer(
            name = request.form.get('name'),
            company = request.form.get('company'),
            phone = phone,
            email = request.form.get('email'),
            gst = request.form.get('gst'),
            address = request.form.get('address'),
            businessType = request.form.get('businessType')
        )
        db.session.add(new_customer)
        db.session.commit()

        return render_template('add_customer.html', success = True)
    return render_template('add_customer.html')



@app.route('/add_inventory', methods=['GET', 'POST'])
def add_inventory():
    #this function will be used to create new inventory item.
    if request.method == 'POST':
        hsn = request.form.get('hsn')
        existing = item.query.filter_by(hsn = hsn).first()
        if existing:
            return render_template('add_inventory.html', duplicate = True)

        new_item = item(
            name = request.form.get('name'),
            hsn = request.form.get('hsn'),
            unitPrice = float(request.form.get('unitPrice')),
            quantity = int(request.form.get('quantity')),
            taxPercentage = float(request.form.get('taxPercentage') or 0)
        )

        db.session.add(new_item)
        db.session.commit()
        return render_template('add_inventory.html', success = True)

    return render_template('add_inventory.html')


@app.route('/select_customer')
def select_customer():
    query = request.args.get('q' , '').lower()
    customers = customer.query.all()


    if query:
        customers = [
            c for c in customers
            if query in c.name.lower() or query in c.phone or query in c.company.lower()
        ]
        return render_template('select_customer.html', customers = customers)

    return render_template('select_customer.html')

@app.route('/view_inventory')
def view_inventory():
    query = request.args.get('q', '').lower()
    inventory = item.query.all()
    if query:
        inventory = [
            item for item in inventory
            if query in item.name.lower() or query in item.hsn
        ]
    return render_template('view_inventory.html', inventory=inventory)



@app.route('/create-bill', methods = ['GET', 'POST'])
def start_bill():

    if request.method == 'POST':
        if 'description[]' in request.form:
            selected_phone = request.form.get('customer_phone')
            selected_customer = customer.query.filter_by(phone = selected_phone).first()

            descriptions = request.form.getlist('description[]')
            quantities = request.form.getlist('quantity[]')
            rates = request.form.getlist('rate[]')
            taxes = request.form.getlist('tax[]')

            total = 0

            item_rows = []

            for desc, qty, rate, tax in zip(descriptions, quantities, rates, taxes):
                qty = int(qty)
                rate = float(rate or 0)
                tax = float(tax or 0)
                subtotal = qty * rate
                tax_amt = subtotal * (tax / 100)
                line_total = subtotal + tax_amt
                total += line_total
                item_rows.append([desc, qty, rate, tax, line_total])

            #creating invoice entry
            new_invoice = invoice(
                customerId = selected_customer.id,
                createdAt = datetime.utcnow(),
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

            for desc, qty, rate, tax, line_total in item_rows:
                matched_item = item.query.filter_by(name = desc).first()
                if matched_item:
                    item_id = matched_item.id
                else:
                    new_item = item(
                        name = desc,
                        hsn = 'N/A', #place holder for future
                        unitPrice = rate,
                        quantity = 0,
                        taxPercentage = tax
                    )
                    db.session.add(new_item)
                    db.session.commit()
                    item_id = new_item.id

                db.session.add(invoiceItem(
                    invoiceId = new_invoice.id,
                    itemId = item_id,
                    quantity = qty,
                    rate = rate,
                    discount = 0,
                    taxPercentage = tax,
                    line_total = line_total
                ))

            db.session.commit()

            return render_template(
                'create_bill.html',
                customer = selected_customer,
                inventory = item.query.all(),
                success = True,
                filename = pdf_filename,
                descriptions = descriptions,
                quantities = quantities,
                rates = rates,
                taxes = taxes,
                total = total
            )

        else:
            selected_phone = request.form.get("customer")
            selected_customer = customer.query.filter_by(phone = selected_phone).first()
            return render_template('create_bill.html', customer = selected_customer, inventory=item.query.all())

    return render_template('select_customer.html')



@app.route('/view_customers')
def view_customers():

    query = request.args.get('q','').lower()
    customers = customer.query.all()

    if query:
        customers = [
            c for c in customers
            if query in c.name.lower() or query in c.phone or query in c.company.lower()
        ]

    return render_template('view_customers.html', customers=customers)


@app.route('/view_bills')
def view_bills():
    query = request.args.get('q', '').lower()
    phone = request.args.get('phone')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    invoices = invoice.query.options(joinedload(invoice.customer)).all()

    results = []

    for inv in invoices:
        customer = inv.customer
        dateStr = inv.createdAt.strftime('%m/%d/%Y')
        invoiceFilename = f"{inv.invoiceId}.pdf"
        record = {
            "invoice_no" : inv.invoiceId,
            "date" : dateStr,
            "customer_name" : customer.name,
            "phone" : customer.phone,
            "total" : f"{inv.totalAmount: ,.2f}",
            "filename" : invoiceFilename
        }
        results.append(record)

    bills = results #default

    if phone:
        bills = [b for b in results if b.get('phone') == phone]
    elif query:
        bills = [
            b for b in results
            if query in b['customer_name'].lower() or query in b.get('phone', '') or query in b['invoice_no']
        ]
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        bills = [b for b in results if start <= datetime.strptime(b['date'], '%Y-%m-%d').date() <= end]
    except Exception as e:
        pass

    return render_template('view_bills.html', bills=bills)

@app.route('/bill_preview/<invoicenumber>')
def bill_preview(invoicenumber):
    current_invoice = invoice.query.filter_by(invoiceId = invoicenumber).first()
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

    return render_template('bill_preview.html', invoice = current_invoice, customer = current_customer, items = item_data)




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

    return render_template('bill_preview.html', invoice = current_invoice, customer = current_customer, items=item_data)



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

    html_content = render_template(
        'bill_preview.html',
        invoice = current_invoice,
        customer = current_customer,
        items = item_data
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