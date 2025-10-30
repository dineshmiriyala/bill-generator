import json
from datetime import datetime, timezone


def _read_info_json(module):
    info_path = module.get_info_json_path()
    with open(info_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_info_json_uses_earliest_invoice(app_module):
    module = app_module
    early_dt = datetime(2021, 5, 17, 9, 30, tzinfo=timezone.utc)

    with module.app.app_context():
        # Seed a customer and an early invoice before regenerating info.json
        cust = module.customer(name="Test Customer", phone="9990011111")
        module.db.session.add(cust)
        module.db.session.commit()

        invoice = module.invoice(
            invoiceId="INV-0001",
            customerId=cust.id,
            createdAt=early_dt,
            pdfPath="static/pdfs/inv-0001.pdf",
            totalAmount=150.0,
        )
        module.db.session.add(invoice)
        module.db.session.commit()

        info_path = module.get_info_json_path()
        if info_path.exists():
            info_path.unlink()

        module.ensure_info_json()
        payload = _read_info_json(module)

    expected_iso = early_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    expected_human = early_dt.strftime("%d %B %Y")

    data_section = payload["data"]
    assert data_section["account_defaults"]["start_date"] == expected_iso
    assert data_section["meta"]["created_on"] == expected_iso
    assert payload["created_on"] == expected_human


def test_create_bill_endpoint_creates_invoice(app_module):
    module = app_module
    with module.app.app_context():
        customer = module.customer(name="Invoice User", phone="5551230000")
        module.db.session.add(customer)
        module.db.session.commit()

        client = module.app.test_client()
        form_payload = {
            "customer_phone": customer.phone,
            "description[]": ["Service A"],
            "quantity[]": ["2"],
            "rate[]": ["450.00"],
            "total[]": ["900.00"],
            "rounded[]": ["0"],
            "dc_no[]": [""],
        }

        response = client.post("/create-bill", data=form_payload, follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["Location"].startswith("/view-bill/")

        created_invoice = module.invoice.query.filter_by(customerId=customer.id).one()
        assert created_invoice.totalAmount == 900.0
        assert created_invoice.invoiceId.startswith("SLP-")

        items = module.invoiceItem.query.filter_by(invoiceId=created_invoice.id).all()
        assert len(items) == 1
        assert items[0].quantity == 2
        assert items[0].rate == 450.0
