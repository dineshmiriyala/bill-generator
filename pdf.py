from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

def generate_invoice_pdf(
    filename,
    invoice_no,
    date,
    seller,
    customer,
    items,
    total
):
    c = canvas.Canvas(filename, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 12)

    # Header
    c.drawString(50, height - 50, "TAX INVOICE")
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 70, f"Invoice No: {invoice_no}")
    c.drawString(300, height - 70, f"Date: {date}")
    c.drawString(50, height - 85, f"Place of Supply: {seller.get('place')}")
    c.drawString(300, height - 85, f"Reverse Charge: {seller.get('reverse_charge')}")

    # Seller Details
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, height - 110, "From:")
    c.setFont("Helvetica", 9)
    c.drawString(50, height - 125, seller.get("name"))
    c.drawString(50, height - 140, seller.get("address"))
    c.drawString(50, height - 155, f"GSTIN: {seller.get('gst')}")
    c.drawString(50, height - 170, f"Phone: {seller.get('phone')}")

    # Buyer Details
    c.setFont("Helvetica-Bold", 10)
    c.drawString(300, height - 110, "To:")
    c.setFont("Helvetica", 9)
    c.drawString(300, height - 125, customer.get("name"))
    c.drawString(300, height - 140, customer.get("address"))
    c.drawString(300, height - 155, f"GSTIN: {customer.get('gst')}")
    c.drawString(300, height - 170, f"Phone: {customer.get('phone')}")

    # Table Header
    c.setFont("Helvetica-Bold", 9)
    headers = ["Description", "HSN", "Qty", "Rate", "Disc.%", "Tax%", "Amount"]
    x_positions = [50, 200, 250, 300, 350, 400, 450]
    y = height - 200
    for i, h in enumerate(headers):
        c.drawString(x_positions[i], y, h)

    # Table Items
    c.setFont("Helvetica", 9)
    y -= 15
    for desc, hsn, qty, rate, disc, tax, amount in items:
        data = [desc, hsn, str(qty), f"{rate:.2f}", f"{disc}%", f"{tax}%", f"{amount:.2f}"]
        for i, d in enumerate(data):
            c.drawString(x_positions[i], y, d)
        y -= 15

    # Total
    c.setFont("Helvetica-Bold", 10)
    c.drawString(350, y - 20, f"Total: INR {total:,.2f}")

    c.setFont("Helvetica", 8)
    c.drawString(50, y - 50, "This is a computer-generated invoice. No signature required.")

    c.save()