from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    company = db.Column(db.String(50))
    phone = db.Column(db.String(50), nullable=False, unique=True)
    email = db.Column(db.String(50))
    gst = db.Column(db.String(30))
    address = db.Column(db.Text)
    businessType = db.Column(db.String(50))
    invoices = db.relationship("invoice", backref="customer", lazy= True)
    createdAt = db.Column(db.DateTime, default=datetime.utcnow())

class invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoiceId = db.Column(db.String(50), unique=True, nullable=False)
    customerId = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    createdAt = db.Column(db.DateTime, default=datetime.utcnow)
    pdfPath = db.Column(db.String(255), nullable=False)
    totalAmount = db.Column(db.Float, nullable=False)
    items = db.relationship("invoiceItem", backref="invoice", lazy=True)

class item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    hsn = db.Column(db.String(50))
    unitPrice = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Float, default=1)
    taxPercentage = db.Column(db.Float)

class invoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoiceId = db.Column(db.String, db.ForeignKey("invoice.id"), nullable=False)
    itemId = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    rate = db.Column(db.Float, nullable = False)
    discount = db.Column(db.Float, default = 0.0)
    taxPercentage = db.Column(db.Float, default = 0.0)
    line_total = db.Column(db.Float, nullable=False)

class role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique = True , nullable=False)
    description = db.Column(db.String(255))
    users = db.relationship("user", backref="role", lazy=True)

class user(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique = True , nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(50), unique = True)
    role_id = db.Column(db.Integer, db.ForeignKey("role.id"))
    is_active = db.Column(db.Boolean, default = True)
    is_admin = db.Column(db.Boolean, default = False)

