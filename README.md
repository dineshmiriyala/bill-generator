# Bill Generator

Bill Generator is a production-ready, local-first invoicing platform designed for print shops and small businesses that need fast, reliable billing without giving up ownership of their data. The application delivers a polished multi-step bill creation experience, deep configuration, detailed statements, analytics, and multiple backup strategies while remaining easy to deploy on a workstation or packaged as a desktop app.

## Table of Contents
- [Overview](#overview)
- [Feature Highlights](#feature-highlights)
- [Architecture Overview](#architecture-overview)
- [Getting Started](#getting-started)
- [Configuration and Onboarding](#configuration-and-onboarding)
- [Daily Operations](#daily-operations)
- [Data Management and Recovery](#data-management-and-recovery)
- [Supabase Synchronisation](#supabase-synchronisation)
- [API Reference](#api-reference)
- [Project Layout](#project-layout)
- [Development Notes](#development-notes)
- [Recent Changes](#recent-changes)
- [License](#license)

## Overview

Bill Generator is built on Flask, SQLAlchemy, and SQLite with a responsive Bootstrap/Jinja front end. The application stores everything locally by default, but supports cloud mirroring via Supabase and automated off-site backups. Key use cases include:

- High-volume invoice creation with configurable rounding logic and printable previews.
- Customer, inventory, and payment management with role-aware edit controls.
- Statement exports (CSV/XLSX) and analytics suited for monthly or annual reporting.
- Self-service recovery tools, automated backup retention, and remote sync for peace of mind.

## Feature Highlights

### Onboarding and Configuration
- Guided onboarding wizard populates core business identity, banking, and payment preferences.
- `info.json` stores all account settings; a dedicated Account Settings screen provides modal editors for each section.
- “Reload Settings” action hot-reloads configuration into the running app without a restart.
- Configurable `file_location` tells the system where to mirror database backups outside the application directory.

### Billing and Inventory
- Three-step bill creation flow: select/create customer, add items with live totals, preview and confirm.
- After you pick a customer, the create bill page also shows that customer's older bills in a side panel.
- Each older bill shows invoice number, date, total amount, paid or pending status, and item count.
- Click any older bill in that panel to open a simple item list with unit price and add those items into the current invoice without leaving the create bill page.
- Smart rounding: individual line items can be rounded to the nearest 10 with visual indicators and precise Decimal back-end calculations.
- Editable totals with automatic recomputation of rate/quantity depending on the last edited field.
- Inventory manager with SKU auto-assignment and duplicate detection.

### Customer Management
- Full CRUD for customers with soft-delete support and duplicate prevention (phone + company/name).
- Dedicated “About Customer” view summarises history and a recovery centre for restoring deleted customers or invoices.

### Statements and Analytics
- Date-range and company statements with CSV/XLSX export that include payment summaries and disclaimers.
- Statement APIs for dashboards and raw invoice exports.
- Accounting statement view that blends ledger totals, per-customer breakdowns, printable invoices, and export-ready PDF/CSV output with per-customer invoice & payment tables.
- Analytics dashboard summarising trends by day, month, year, weekday, and top customers using precomputed aggregates.

### Accounting & Cashflow
- Dedicated `/accounting` workspace summarises outstanding invoices, total income/expenses, and recent ledger entries.
- Record incoming payments or expenses (with itemised breakdowns) that link back to customers and invoices.
- Automatic transaction IDs (`SLP-TXN-DDMMYY-######`) keep records ordered without manual effort.

### Document Layout and Rendering
- Configurable “Invoice Visual Settings” (Config → Invoice Visual Settings) let you tune watermark colour and section font sizes stored in the database (`layoutConfig`).
- Print-ready HTML templates for invoice previews and final statements.
- Invoice preview now always opens in the default A4 layout, without extra size choices.
- Optional exclusion of customer contact details on rendered invoices.

### Payments and Integrations
- Built-in UPI QR generator (UI + REST endpoint) for instant payment links.
- Supabase integration for full or incremental database + analytics uploads, with health checks and detailed feedback.

### Backups and Recovery
- Automatic SQLite backups retained in `db/backups` (latest 10 copies) with 7-day freshness checks at shutdown.
- Optional mirroring of every backup (automatic and manual) to the configured `file_location` outside the application sandbox.
- Manual “Make Local DB Copy” action in the Account menu for on-demand mirroring.

## Architecture Overview

- **Backend:** Flask application (`app.py`) with blueprints for AJAX/REST APIs (`api.py`).
- **Database:** SQLite via SQLAlchemy models defined in `db/models.py`, with Flask-Migrate handling schema migrations.
- **Front end:** Jinja templates under `templates/` paired with Bootstrap, custom JavaScript, and CSS assets in `static/`.
- **Analytics:** Aggregation helpers in `analytics.py` and client-side views using Chart.js (bundled in static assets).
- **Config storage:** `info.json` (in `db/` for server mode, user data directory for packaged desktop mode) governs business settings.
- **Backups:** Local backup helpers in `app.py` create timestamped `.bak` files and handle pruning/local mirroring.
- **Supabase upload:** `supabase_upload.py` orchestrates full/incremental sync with error reporting and metadata tracking.

## Getting Started

### Prerequisites
- Python 3.11 or later (exact version should match the environment used in production).
- SQLite (bundled with Python on macOS, Windows, and most Linux distributions).
- Node.js is **not** required; front-end assets are pre-built.

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/dineshmiriyala/bill-generator.git
   cd bill-generator
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # On Windows use: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Running the App
```bash
python app.py
```
The development server listens on `http://127.0.0.1:42069/` by default. For LAN access, browse to `http://<machine-ip>:42069/`. On first launch, the onboarding workflow will guide you through initial setup.

### Desktop Packaging
For Windows packaging the project ships a `build_exe.bat` script that wraps PyInstaller to produce a standalone executable. Before packaging, run `pytest` to ensure the latest test suite passes, then execute:

```
build_exe.bat
```

The script installs/updates dependencies, clears previous artefacts, and emits `BillGenerator_V4.0.exe` under `dist/`. Launch the generated binary from `cmd.exe` or PowerShell for first-run smoke testing so any console logs remain visible.

## Configuration and Onboarding

- **Onboarding screen:** Captures business name, owner details, GSTIN, address, UPI ID, and optional banking information. Completing onboarding writes `info.json`, marks onboarding as complete, and unlocks the rest of the application.
- **Account Settings (`/config`):** Cards and modals expose each configuration slice (business, bank, UPI, invoice layout, payment terms, services, Supabase credentials, backup folder). Submit changes and refresh the live application state using “Reload Settings”.
- **Configuration file (`info.json`):**
  - `business`, `bank`, `payment`, `statement`, `services`, `bill_config`, `upi_info`, `appearance`, and `account_defaults` power the UI and exports.
  - `supabase` holds `url`, `key`, and last upload timestamps.
  - `file_location` identifies the external folder used for mirrored `.bak` files.
  - `onboarding_complete` toggles access to the rest of the app.

## Daily Operations

1. **Create or edit customers** from `/create_customers` or `/view_customers`. Soft deletes can be reversed from the recovery centre.
2. **Manage inventory** via `/add_inventory` and `/view_inventory`. SKUs are auto-generated if omitted.
3. **Generate invoices:**
   - Start at `/select_customer` to pick or create a customer.
   - On the create bill page, you can also see the selected customer's previous bills on the right side.
   - Click an older bill to open a simple item list with unit price and add those items into the current invoice.
   - Add items, apply rounding, edit totals, and preview the invoice.
   - Finalise to persist an `invoice`, individual `invoiceItem` records, and a printable HTML page accessible from `/view_bills`.
4. **Edit or delete invoices** with admin privileges only. Edits respect previous rounding choices and preserve totals on reload.
5. **Statements:** Use `/statements` (date range) or `/statements_company` (per customer) to review totals and export data.
6. **Analytics:** `/analytics` surfaces trends, retention, and top customers for monitoring business health.
7. **Invoice visuals:** Use the Config → Invoice Visual Settings panel to update watermark colour and section font sizes (persisted via `layoutConfig`).
8. **Accounting:** Head to `/accounting` to monitor receivables and log payments/expenses against customers and invoices.

## Data Management and Recovery

- **Automatic backups:** Every time a backup is created (before Supabase sync or during the seven-day staleness check) a timestamped copy lands in `db/backups/`. Old backups beyond the ten most recent are pruned automatically.
- **External mirroring:** If `file_location` is set, each automatic backup is mirrored to that directory, and only the latest ten copies are retained. Manual backups triggered from the UI also use this folder.
- **Manual copy:** From the “More → Account & Insights” menu, click “Make Local DB Copy” to immediately mirror the current database. The button is enabled once a backup folder has been configured.
- **Recovery centre:** `/recover` lists soft-deleted customers and invoices with one-click restoration.

## Supabase Synchronisation

- **Full upload:** “Upload All Data to Supabase” performs a complete database sync, preceded by local backup creation, and now includes `accounting_transaction` rows alongside customers/items/invoices. Connectivity is verified before transfer and the modal keeps the sync log visible until you dismiss it.
- **Incremental sync:** `/supabase_sync_incremental` (invoked from the UI) sends only new or changed records along with analytics logs.
- **Metadata tracking:** Successful uploads update `info.json` (`supabase.last_uploaded` / `last_incremental_uploaded`) so the home page can surface the last sync time.

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/bill_items/<invoice_no>` | GET | Returns customer, line items, and totals for an invoice as JSON. |
| `/api/generate_upi_qr` | GET | Generates a base64 encoded SVG for a UPI payment QR code. Query params: `upi_id` (required), `am` (amount), `pn` (payee name), `cu` (currency, defaults to `INR`). Legacy `amount`/`name`/`cur` are still accepted. |
| `/accounting/customer_summary/<customer_id>` | GET | Returns a JSON snapshot of invoiced/paid/outgoing totals and balance for a specific customer. |
| `/accounting/amount_to_words` | GET | Converts a numeric amount to words (Rupees). Query param: `amount`. |
| `/api/statements` | GET | JSON summary of statements for a date range or year/month scope, including totals and per-period breakdowns. |
| `/api/statements/invoices` | GET | Paginated raw invoice data for reporting/export. |
| `/analytics_event` | POST | Records analytics events emitted from the front end. |

All API endpoints require the application to be running locally. Authentication is not enforced because the app is intended for trusted LAN/desktop environments.

## Project Layout

```
├── app.py                 # Main Flask application and routes
├── analytics.py           # Analytics aggregation helpers
├── analytics_tracking.py  # Event logging
├── api.py                 # JSON/QR code endpoints
├── bg_app/                # Future modular routes/services
├── db/
│   ├── models.py          # SQLAlchemy models
│   └── migrations/        # Alembic migration scripts
├── templates/             # Jinja templates (UI, onboarding, config, invoices)
├── static/                # CSS/JS assets and images
├── supabase_upload.py     # Supabase integration helpers
├── requirements.txt       # Python dependencies
└── build/ / dist/         # Build artefacts for packaged releases
```

## Development Notes

- **Database migrations:** Use Flask-Migrate commands (e.g., `flask db migrate`, `flask db upgrade`) to evolve the schema. The app runs `migrate_db()` on startup to ensure the SQLite file is up to date.
- **Testing:** Automated coverage lives under `tests/`; run `pytest` before raising PRs or cutting releases.
- **Coding standards:** The codebase targets Python 3.11, uses type hints in newer modules, and prefers Decimal for currency math. Follow existing patterns when contributing.
- **Packaging:** When building desktop distributions, set the `BG_DESKTOP_ENV=1` environment variable so the data directory resolves to the user’s application support folder. The provided `build_exe.bat` handles this automatically for Windows builds.

## Recent Changes

### 2026-03-28 11:35:39 IST (+0530)
- Bill preview now opens only in the default A4 layout.
- The extra A5 and tiny bill preview routes and size picker were removed.
- The A4 preview layout, print button, and QR toggle stay the same.

### 2026-03-28 10:55:36 IST (+0530)
- The create bill page now uses more desktop space so the customer, invoice, items, and total cards feel less cramped.
- The previous bills panel is now wider on large screens so older bill items are easier to read.
- Older bill item details now show only the item name and unit price, and the page no longer shows the extra round note or the repeated customer bill count near the action buttons.
- The red remove control is now a compact `-` button, and the items row stays usable even when Delivery Challan is turned on.
- The create bill header is now cleaner, with the repeated customer name and top change-customer button removed.
- The item header labels are easier to read now, and the red `-` button is square with the same height as the Round button.
- The item row now fits without horizontal scrolling, so the action buttons stay visible and the top labels are not clipped.
- The customer details card text is simpler now, the ID label says `ID/Phone`, and `Latest Bill Date` is now `Last Bill Date`.
- The current bill's invoice number is no longer shown in the create or edit page cards and banners.
- The new invoice item rows now have more breathing room, and the total card now shows only the main total amount.
- Previous bill items now have an `Add` button that brings that item into the current invoice, keeps the old unit price, and moves the cursor straight to the quantity field.
- Expanded previous bill items now use a stacked readable layout, so long item names are much easier to scan before adding them.

### 2026-03-27 16:38:40 IST (+0530)
- The create bill page now shows previous bills for the selected customer.
- Each previous bill shows invoice number, date, total amount, paid or pending status, and item count.
- Click any previous bill to load its items inside the same page.
- The create bill page now uses a more dashboard-like layout with a bill history side panel, top info cards, a full invoice items section, and a separate total card.
- The item editor now uses a wider layout on larger screens so the fields feel less cramped.
- The action buttons in each item row now stay inside their own space instead of spilling out.
- When you edit a bill, that current bill is hidden from the previous bills list so you only see the other bills for that customer.

## License

This project is licensed under the MIT License. See `LICENSE` for details.
