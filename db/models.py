from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import event, func, select
import json

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
    invoices = db.relationship("invoice", backref="customer", lazy=True)
    createdAt = db.Column(db.DateTime, default=datetime.utcnow)
    isDeleted = db.Column(db.Boolean, nullable=False, default=False, index=True)
    deletedAt = db.Column(db.DateTime, nullable=True, index=True)

    @classmethod
    def alive(cls):
        return cls.query.filter_by(isDeleted=False)


class invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoiceId = db.Column(db.String(50), unique=True, nullable=False)
    customerId = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False, index=True)
    createdAt = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    pdfPath = db.Column(db.String(255), nullable=False)
    totalAmount = db.Column(db.Float, nullable=False)
    items = db.relationship("invoiceItem", backref="invoice", lazy=True)
    isDeleted = db.Column(db.Boolean, nullable=False, default=False, index=True)
    deletedAt = db.Column(db.DateTime, nullable=True, index=True)
    exclude_phone = db.Column(db.Boolean, default=False)
    exclude_gst = db.Column(db.Boolean, default=False)
    exclude_addr = db.Column(db.Boolean, default=False)

    @classmethod
    def alive(cls):
        return cls.query.filter_by(isDeleted=False)


class item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, index=True)
    sku = db.Column(db.Integer, unique=True, index=True, nullable=True)
    unitPrice = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Float, default=1)
    taxPercentage = db.Column(db.Float)


# Auto-assign an incrementing SKU if not provided
@event.listens_for(item, 'before_insert')
def set_incremental_sku(mapper, connection, target):
    if target.sku is None:
        max_sku = connection.execute(select(func.max(item.sku))).scalar()
        target.sku = (max_sku or 0) + 1


class invoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoiceId = db.Column(db.String, db.ForeignKey("invoice.id"), nullable=False, index=True)
    itemId = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False, index=True)
    dcNo = db.Column(db.String(64), nullable=True, index=True)
    quantity = db.Column(db.Integer, default=1)
    rate = db.Column(db.Float, nullable=False)
    discount = db.Column(db.Float, default=0.0)
    taxPercentage = db.Column(db.Float, default=0.0)
    line_total = db.Column(db.Float, nullable=False)


class role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255))
    users = db.relationship("user", backref="role", lazy=True)


class user(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(50), unique=True)
    role_id = db.Column(db.Integer, db.ForeignKey("role.id"))
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)


class lastBackup(db.Model):
    __tablename__ = "last_backup"

    id = db.Column(db.Integer, primary_key=True)
    occurred_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    note = db.Column(db.String(255))

    # audit fields
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


class layoutConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sizes_json = db.Column(db.Text, nullable=False, default=json.dumps({
        "header": 13,
        "customer": 16,
        "table": 13,
        "totals": 15,
        "payment": 13,
        "footer": 10,
        "invoice_info": 13
    }))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    def get_sizes(self):
        """Return sizes as Python Dictionary."""
        try:
            return json.loads(self.sizes_json)
        except (ValueError, TypeError):
            return {}

    def set_sizes(self, sizes: dict):
        """Store sizes dict as json string."""
        self.sizes_json = json.dumps(sizes)

    def reset_sizes(self):
        """Reset sizes to default values and save."""
        default_sizes = {
            "header": 13,
            "customer": 16,
            "table": 13,
            "totals": 15,
            "payment": 13,
            "footer": 10,
            "invoice_info": 13
        }
        self.set_sizes(default_sizes)
        db.session.commit()

    @classmethod
    def get_or_create(cls, sizes: dict = None):
        """Return layout config instance or create if it doesn't exist."""
        instance = cls.query.first()
        if not instance:
            instance = cls()
            if sizes:
                instance.set_sizes(sizes)
            db.session.add(instance)
            db.session.commit()
        return instance


db.Index('ix_invoiceItem_invoice_item', invoiceItem.invoiceId, invoiceItem.itemId)
