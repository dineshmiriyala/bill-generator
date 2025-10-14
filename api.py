from flask import Blueprint, jsonify
from db.models import invoice, invoiceItem, item

api_bp = Blueprint('api_bp', __name__)

@api_bp.route('/api/bill_items/<invoicenumber>')
def api_bill_items(invoicenumber):
    """
    Return JSON list of all items in an invoice.
    """
    inv = invoice.query.filter_by(invoiceId=invoicenumber, isDeleted=False).first()
    if not inv:
        return jsonify({"error": "Invoice Not Found"}), 404

    items = (
        invoiceItem.query
        .filter_by(invoiceId=inv.id)
        .join(item, invoiceItem.itemId == item.id)
        .add_columns(
            item.name.label("item_name"),
            invoiceItem.quantity,
            invoiceItem.rate,
            invoiceItem.taxPercentage,
            invoiceItem.line_total
        )
        .all()
    )

    rows = []
    for i in items:
        rows.append({
            "name": i.item_name,
            "quantity": i.quantity,
            "rate": round(i.rate or 0, 2),
            "tax": round(i.taxPercentage or 0, 2),
            "amount": round(i.line_total or 0, 2)
        })

    return jsonify({
        "invoice_no": inv.invoiceId,
        "customer": inv.customer.name if inv.customer else "Unknown",
        "items": rows,
        "total": round(inv.totalAmount or 0, 2)
    })