import json
from datetime import datetime, timezone
import re


def _read_info_json(module):
    info_path = module.get_info_json_path()
    with open(info_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _seed_invoice(module, cust, invoice_no, total_amount, created_at, *, is_deleted=False, is_paid=False, item_names=None):
    item_names = item_names or ["Seed Item"]

    inv = module.invoice(
        invoiceId=invoice_no,
        customerId=cust.id,
        createdAt=created_at,
        pdfPath=f"static/pdfs/{invoice_no}.pdf",
        totalAmount=total_amount,
        isDeleted=is_deleted,
        payment=is_paid,
    )
    module.db.session.add(inv)
    module.db.session.flush()

    line_total = round(float(total_amount) / max(len(item_names), 1), 2)
    for index, item_name in enumerate(item_names, start=1):
        inventory_item = module.item.query.filter_by(name=item_name).first()
        if not inventory_item:
            inventory_item = module.item(
                name=item_name,
                unitPrice=line_total,
                quantity=10,
                taxPercentage=0,
            )
            module.db.session.add(inventory_item)
            module.db.session.flush()

        module.db.session.add(module.invoiceItem(
            invoiceId=inv.id,
            itemId=inventory_item.id,
            quantity=index,
            rate=line_total,
            discount=0,
            taxPercentage=0,
            line_total=line_total,
        ))

    return inv


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

        # Step 1: load the create bill form for this customer to obtain the form token
        form_resp = client.post(
            "/select_customer",
            data={"customer": customer.phone},
            follow_redirects=False,
        )
        html = form_resp.get_data(as_text=True)
        match = re.search(r'name="form_token" value="([^"]+)"', html)
        assert match, "form token not rendered"
        token = match.group(1)

        form_payload = {
            "customer_phone": customer.phone,
            "description[]": ["Service A"],
            "quantity[]": ["2"],
            "rate[]": ["450.00"],
            "total[]": ["900.00"],
            "rounded[]": ["0"],
            "dc_no[]": [""],
            "form_token": token,
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


def test_create_bill_page_shows_previous_bills_for_selected_customer(app_module):
    module = app_module
    with module.app.app_context():
        cust = module.customer(name="History User", company="History Co", phone="5550001111")
        module.db.session.add(cust)
        module.db.session.commit()

        _seed_invoice(
            module,
            cust,
            "INV-HIST-001",
            125.0,
            datetime(2026, 3, 25, 9, 0, tzinfo=timezone.utc),
            item_names=["Poster"],
        )
        _seed_invoice(
            module,
            cust,
            "INV-HIST-002",
            300.0,
            datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc),
            is_paid=True,
            item_names=["Banner", "Sticker"],
        )
        module.db.session.commit()

        client = module.app.test_client()
        response = client.post("/select_customer", data={"customer": cust.phone}, follow_redirects=False)

        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Previous Bills" in html
        assert 'data-history-invoice="INV-HIST-001"' in html
        assert 'data-history-invoice="INV-HIST-002"' in html
        assert "INR 125.00" in html
        assert "2 items" in html


def test_create_bill_history_hides_soft_deleted_invoices(app_module):
    module = app_module
    with module.app.app_context():
        cust = module.customer(name="Soft Delete User", company="Filter Co", phone="5550002222")
        module.db.session.add(cust)
        module.db.session.commit()

        _seed_invoice(
            module,
            cust,
            "INV-LIVE-001",
            200.0,
            datetime(2026, 3, 24, 8, 0, tzinfo=timezone.utc),
            item_names=["Cards"],
        )
        _seed_invoice(
            module,
            cust,
            "INV-DELETED-001",
            400.0,
            datetime(2026, 3, 24, 9, 0, tzinfo=timezone.utc),
            is_deleted=True,
            item_names=["Flex"],
        )
        module.db.session.commit()

        client = module.app.test_client()
        response = client.get(f"/create-bill?customer_id={cust.id}", follow_redirects=False)

        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'data-history-invoice="INV-LIVE-001"' in html
        assert 'data-history-invoice="INV-DELETED-001"' not in html


def test_edit_bill_history_excludes_current_invoice(app_module):
    module = app_module
    with module.app.app_context():
        cust = module.customer(name="Edit User", company="Edit Co", phone="5550003333")
        module.db.session.add(cust)
        module.db.session.commit()

        current_invoice = _seed_invoice(
            module,
            cust,
            "INV-CURRENT-001",
            500.0,
            datetime(2026, 3, 27, 7, 0, tzinfo=timezone.utc),
            item_names=["Magazine"],
        )
        _seed_invoice(
            module,
            cust,
            "INV-OLDER-001",
            275.0,
            datetime(2026, 3, 21, 7, 0, tzinfo=timezone.utc),
            item_names=["Flyer"],
        )
        module.db.session.commit()

        client = module.app.test_client()
        response = client.get(f"/edit-bill/{current_invoice.invoiceId}", follow_redirects=False)

        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'data-history-invoice="INV-OLDER-001"' in html
        assert 'data-history-invoice="INV-CURRENT-001"' not in html
