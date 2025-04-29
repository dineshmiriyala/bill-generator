# 🧾 Bill Generator Web App

This is a lightweight, minimalist web application for generating and managing professional invoices. Built with **Flask** and **Bootstrap**, the app supports customer management, bill creation, PDF generation, and a smooth step-by-step flow for day-to-day billing operations.

---

## 🚀 Features

- 🧍 **Customer Management**
  - Add, view, and search customers
  - Prevent duplicate entries using phone number as key

- 🧾 **Bill Creation**
  - Select or add a customer before generating a bill
  - Add multiple line items with quantity, rate, and tax
  - Calculate total dynamically
  - Save bill records for viewing later

- 📄 **PDF Export (planned)**
  - Generate invoice-style PDF with customer and billing details

- 🔎 **Search & Filter**
  - Search bills by name, phone, invoice number
  - Filter by date range

- ✅ **Responsive UI**
  - Built with Bootstrap 5
  - Works smoothly on desktop and mobile

---

## 🛠 Tech Stack

- **Python 3.x**
- **Flask** (Web Framework)
- **Jinja2** (Templating)
- **Bootstrap 5** (Frontend CSS Framework)
- **WeasyPrint / wkhtmltopdf** (for future PDF generation)
- **SQLite or JSON/CSV** (planned for persistent storage)

---

## 📂 Project Structure

```bash
.
├── app.py                  # Main Flask app
├── templates/              # HTML Templates
│   ├── base.html
│   ├── home.html
│   ├── add_customer.html
│   ├── view_customers.html
│   ├── select_customer.html
│   ├── create_bill.html
│   └── view_bills.html
├── static/                 # Static assets
│   ├── css/
│   ├── js/
│   └── pdfs/               # PDF output folder
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

```bash
# 1. Clone the repo
git clone https://github.com/dineshmiriyala/bill-generator.git
cd bill-generator

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the Flask app
python app.py
```

Then open http://127.0.0.1:5000

