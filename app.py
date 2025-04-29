from logging import exception

from flask import Flask, render_template, request
from datetime import datetime


app = Flask(__name__)

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
@app.route('/create_customers')
def add_customers():
    return render_template('add_customer.html')

@app.route('/select_customer')
def select_customer():
    return render_template('select_customer.html')

@app.route('/start-bill', methods = ['GET', 'POST'])
def start_bill():
    customers = [
        {
            "company": "Sri Lakshmi Offset Printers",
            "name": "Hari Nadh Babu Miriyala",
            "phone": "9848992207"
        },
        {
            "company": "MD",
            "name": "Dinesh Miriyala",
            "phone": "7659909852"
        },
        {
            "company": "Sree Ganesh Packaging",
            "name": "Karthik Reddy",
            "phone": "9988776655"
        },
        {
            "company": "Creative Prints",
            "name": "Pooja Sharma",
            "phone": "9123456780"
        },
        {
            "company": "Print World",
            "name": "Arjun Verma",
            "phone": "9001234567"
        },
        {
            "company": "Papertrail Pvt Ltd",
            "name": "Megha Singh",
            "phone": "9876543210"
        }
    ]

    if request.method == 'POST':
        selected_phone = request.form.get('customer')
        customer = next((c for c in customers if c['phone'] == selected_phone), None)
        if customer:
            return render_template('create_bill.html', customer=customer)
        else:
            return render_template('select_customer.html', customers=customers, error = "Customer Not Found.")

    return render_template('select_customer.html', customers=customers)



@app.route('/create-bill', methods=['GET', 'POST'])
def create_bill():
    customers = [
        {
            "company": "Sri Lakshmi Offset Printers",
            "name": "Hari Nadh Babu Miriyala",
            "phone": "9848992207"
        },
        {
            "company": "MD",
            "name": "Dinesh Miriyala",
            "phone": "7659909852"
        },
        {
            "company": "Sree Ganesh Packaging",
            "name": "Karthik Reddy",
            "phone": "9988776655"
        },
        {
            "company": "Creative Prints",
            "name": "Pooja Sharma",
            "phone": "9123456780"
        },
        {
            "company": "Print World",
            "name": "Arjun Verma",
            "phone": "9001234567"
        },
        {
            "company": "Papertrail Pvt Ltd",
            "name": "Megha Singh",
            "phone": "9876543210"
        }
    ]

    if request.method == 'POST':
        customer = request.form.get('customer')
        descriptions = request.form.getlist('description[]')
        quantities = request.form.getlist('quantity[]')
        rates = request.form.getlist('rate[]')
        taxes = request.form.getlist('tax[]')

        # Dummy total calculation (just for backend confirmation)
        total = 0
        for q, r, t in zip(quantities, rates, taxes):
            try:
                subtotal = float(q) * float(r)
                tax_amt = subtotal * float(t) / 100
                total += subtotal + tax_amt
            except ValueError:
                continue

        return render_template('create_bill.html', customers=customers, success=True, total=round(total, 2))

    return render_template('create_bill.html', customers=customers)

@app.route('/view_customers')
def view_customers():
    # load data from DB, for now we'll simulate with dummy data
    query = request.args.get('q','').lower()
    customers = [
        {
            "company": "Sri Lakshmi Offset Printers",
            "name": "Hari Nadh Babu Miriyala",
            "phone": "9848992207",
            "email": "haripress@gmail.com",
            "gst": "22AAAAA0000A1Z5",
            "address": "Pamarru, AP"
        },
        {
            "company": "MD",
            "name": "Dinesh Miriyala",
            "phone": "7659909852",
            "email": "dineshmiriyala9968@gmail.com",
            "gst": "123456789001",
            "address": "Pamarru, AP"
        },
        {
            "company": "Sree Ganesh Packaging",
            "name": "Karthik Reddy",
            "phone": "9988776655",
            "email": "karthik@sgp.com",
            "gst": "36AAACG1234L1Z9",
            "address": "Vijayawada, AP"
        },
        {
            "company": "Creative Prints",
            "name": "Pooja Sharma",
            "phone": "9123456780",
            "email": "pooja@creativeprints.in",
            "gst": "29BBBBB9999M1Z2",
            "address": "Bangalore, KA"
        },
        {
            "company": "Print World",
            "name": "Arjun Verma",
            "phone": "9001234567",
            "email": "arjun@printworld.com",
            "gst": "27CCCCD8888N1Z5",
            "address": "Pune, MH"
        },
        {
            "company": "Papertrail Pvt Ltd",
            "name": "Megha Singh",
            "phone": "9876543210",
            "email": "megha@papertrail.co",
            "gst": "07DDDDD7777O1Z8",
            "address": "New Delhi, DL"
        }
    ]

    if query:
        customers = [
            c for c in customers
            if query in c['name'].lower() or query in c['phone'] or query in c['company'].lower()
        ]

    return render_template('view_customers.html', customers=customers)


@app.route('/bills')
def view_bills():
    query = request.args.get('q', '').lower()
    phone = request.args.get('phone')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    bills = [
        {
            "invoice_no": "3SP25/1727",
            "date": "2025-04-27",
            "customer_name": "Hari Nadh Babu Miriyala",
            "phone": "9848992207",
            "total": "12,450.00",
            "filename": "invoice_1727.pdf"
        },
        {
            "invoice_no": "3SP25/1728",
            "date": "2025-04-28",
            "customer_name": "Dinesh Miriyala",
            "phone": "7659909852",
            "total": "9,850.00",
            "filename": "invoice_1728.pdf"
        },
        {
            "invoice_no": "3SP25/1729",
            "date": "2025-04-29",
            "customer_name": "Hari Nadh Babu Miriyala",
            "phone": "9848992207",
            "total": "15,200.00",
            "filename": "invoice_1729.pdf"
        },
        {
            "invoice_no": "3SP25/1730",
            "date": "2025-04-29",
            "customer_name": "Dinesh Miriyala",
            "phone": "7659909852",
            "total": "7,300.00",
            "filename": "invoice_1730.pdf"
        }
    ]

    if phone:
        bills = [b for b in bills if b.get('phone') == phone]
    elif query:
        bills = [
            b for b in bills
            if query in b['customer_name'].lower() or query in b.get('phone', '') or query in b['invoice_no']
        ]
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        bills = [b for b in bills if start <= datetime.strptime(b['date'], '%Y-%m-%d').date() <= end]
    except Exception as e:
        pass

    return render_template('view_bills.html', bills=bills)



if __name__ == '__main__':
    app.run(debug=True)