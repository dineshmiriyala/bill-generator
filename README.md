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
- Accounting-ledger statements, printable PDFs, and analytics suited for monthly or annual reporting.
- Self-service recovery tools, automated backup retention, and remote sync for peace of mind.

## Feature Highlights

### Onboarding and Configuration
- Guided onboarding wizard populates core business identity, banking, and payment preferences.
- `info.json` stores all account settings; a dedicated Account Settings screen provides modal editors for each section.
- “Reload Settings” action hot-reloads configuration into the running app without a restart.
- Configurable `file_location` tells the system where to mirror database backups outside the application directory.

### Billing and Inventory
- Three-step bill creation flow: select/create customer, add items with live totals, preview and confirm.
- Bills can now be saved as drafts without creating a real invoice yet.
- Drafts stay separate from real invoices until you click `Generate Bill`.
- The create bill page now has `Save Draft` or `Update Draft`, and draft mode also gives a `Delete Draft` action.
- There is a dedicated `Draft Bills` page for opening, searching, and removing active drafts.
- The `Draft Bills` page also supports bulk cleanup, so you can delete all active drafts or all drafts for one customer in one step.
- You can also create a draft straight from an existing bill by using `Duplicate as Draft`.
- After you pick a customer, the create bill page also shows that customer's older bills in a side panel.
- Each older bill shows invoice number, date, total amount, paid or pending status, and item count.
- Click any older bill in that panel to open a simple item list with unit price and add those items into the current invoice without leaving the create bill page.
- The bill detail page now also uses a newer two-column layout with a left-side customer bill list, so moving between that customer's bills is faster.
- The bill detail page now has a `Bill with Dues` flow with a left-side bill list and a right-side summary panel, so staff can pick the current bill and any older unpaid bills before printing.
- Staff can also mark a bill as paid from that `Bill with Dues` page itself without leaving the picker.
- Smart rounding: individual line items can be rounded to the nearest 10 with visual indicators and precise Decimal back-end calculations.
- Editable totals with automatic recomputation of rate/quantity depending on the last edited field.
- Inventory manager with SKU auto-assignment and duplicate detection.

### Customer Management
- Full CRUD for customers with soft-delete support and duplicate prevention (phone + company/name).
- The `Add New Customer` page now uses the same newer card-based layout as the billing pages, so the form is easier to read at a glance.
- When a new customer is created from the bill picker flow, the app now takes you straight back into bill creation for that customer.
- The customer list page now also follows the newer design style, with search-first customer cards instead of the older large table.
- The `About Customer` and `Edit Customer` pages now follow the same newer card layout too, instead of the older plain form pages.
- Dedicated customer profile pages still work alongside the recovery centre for restoring deleted customers or invoices.

### Statements and Analytics
- The full company statement now lives under accounting, with one interactive page and matching PDF exports.
- The company statement now has two clear modes:
  - `Simple`: only invoice rows and one total
  - `Accounting Statement`: invoice list plus the transaction ledger
- The company statement page now uses only a date filter. Customer search is kept on the main accounting page, not on the company statement page.
- Customer statement routes now isolate records only by exact customer id or exact phone. They no longer use fuzzy name or company matching.
- Statement APIs for dashboards and raw invoice exports.
- Print-ready accounting exports exist for the whole company and for a single customer.
- Analytics dashboard summarising trends by day, month, year, weekday, and top customers using precomputed aggregates.

### Accounting & Cashflow
- Dedicated `/accounting` workspace now stays light and search-first, with only the top due customers shown on the main page.
- A separate `/accounting/statement` page now handles the whole-company statement with `Simple` and `Accounting Statement` modes.
- A dedicated customer accounting page shows dues, paid amount, invoices, expandable item details, transactions, and a print/save PDF button.
- That same customer page also has a `Simple Statement` button for the older invoice-only PDF that shows just the bills and the total.
- The customer accounting page also has `+` buttons for invoices and transactions, so staff can start a new bill or open the normal payment/expense modal without leaving that customer page.
- The customer accounting page also has a quick `Mark as Paid` button on each unpaid invoice.
- The home page now has a direct `Add Transaction` button that opens the normal payment or expense modal right there.
- The shared payment modal now keeps loaded bills inside a scrollable bill pane, so long bill lists do not push the save button out of reach.
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
For Windows packaging the project ships a `build_exe.bat` script that wraps PyInstaller to produce a standalone executable.

You only need Python 3 installed on the Windows machine. You do **not** need to create or activate a venv yourself anymore.

The normal flow is:

```
build_exe.bat
```

The script now:
- creates or reuses a local `.build-venv` automatically
- installs or updates the required packages
- installs PyInstaller automatically
- clears old build output
- builds the Windows executable into `dist/`

The final file is:

```text
dist\BillGenerator_V4.5.1.exe
```

The first run can take a little longer because the script may need to create the local build environment and download packages.

## Configuration and Onboarding

- **Onboarding screen:** Captures business name, owner details, GSTIN, address, UPI ID, and optional banking information. Completing onboarding writes `info.json`, marks onboarding as complete, and unlocks the rest of the application.
- **Account Settings (`/config`):** Cards and modals expose each configuration slice (business, bank, UPI, invoice layout, payment terms, services, Supabase credentials, backup folder). Submit changes and refresh the live application state using “Reload Settings”.
- **Invoice settings:** Under `bill_config`, you can choose where the dues table shows on printed bills and also change the dues table heading text without changing the style.
- **Configuration file (`info.json`):**
  - `business`, `bank`, `payment`, `statement`, `services`, `bill_config`, `upi_info`, `appearance`, and `account_defaults` power the UI and exports.
  - `supabase` holds `url`, `key`, and last upload timestamps.
  - `file_location` identifies the external folder used for mirrored `.bak` files.
  - `onboarding_complete` toggles access to the rest of the app.

## Daily Operations

1. **Create or edit customers** from `/create_customers` or `/view_customers`. Soft deletes can be reversed from the recovery centre.
   - If you add a customer from the bill picker flow, the app now returns you straight into bill creation for that new customer.
2. **Manage inventory** via `/add_inventory` and `/view_inventory`. SKUs are auto-generated if omitted.
3. **Generate invoices:**
   - Start at `/select_customer` to pick or create a customer.
   - If that customer already has active drafts, the customer picker now shows a `Drafts` badge and an `Open Drafts` shortcut.
   - On the create bill page, you can also see the selected customer's previous bills on the right side.
   - Click an older bill to open a simple item list with unit price and add those items into the current invoice.
   - Use `Save Draft` if the bill is not ready yet, or reopen older drafts later from the `Draft Bills` page on the home screen.
   - Add items, apply rounding, edit totals, and preview the invoice.
   - The bill detail page now shows the same customer's other bills in a left-side panel, with the current bill highlighted.
   - From the bill detail page, use `Bill with Dues` to choose the current bill and any older unpaid bills, then print one combined summary with one final total.
   - Finalise to persist an `invoice`, individual `invoiceItem` records, and a printable HTML page accessible from `/view_bills`.
4. **Edit or delete invoices** with admin privileges only. Edits respect previous rounding choices and preserve totals on reload.
5. **Company Books:** Use `/accounting/statement` for the whole-company statement page, filters, and print/save PDF.
   - Use the `Simple` tab there if you only want invoice rows and one total.
   - Use the `Accounting Statement` tab there if you want invoices plus transactions for the selected dates.
   - Both company statement invoice lists now have a quick `Mark as Paid` button for unpaid bills.
   - Old `/statements`, `/statements/blank`, `/statements_company`, and `/statements/accounting` links now redirect into the accounting flow.
6. **Analytics:** `/analytics` surfaces trends, retention, and top customers for monitoring business health.
7. **Invoice visuals:** Use the Config → Invoice Visual Settings panel to update watermark colour and section font sizes (persisted via `layoutConfig`).
8. **Accounting:** Head to `/accounting` to see the top due customers and search for any customer directly.
   - Open a customer accounting page to see that customer's due amount, paid amount, compact bill list, expandable bill items, and collapsible transactions.
   - Use `Print / Save PDF` there to open the customer accounting PDF in a printable format.
   - Use `Simple Statement` there if you only want the older simple PDF with invoice rows and one total, without the accounting payment sections.
   - Use the `+` beside bills to start a new bill for that customer right away.
   - Use the `+` beside transactions to open the normal payment/expense modal with that customer already selected.
   - In the transaction modal, you can now load that customer's bills on demand, expand bill items, and select one or more unpaid bills to auto-fill the payment amount.
   - You can also use `Add Transaction` directly from the home page for a faster entry flow.

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
- **Packaging:** Desktop builds use the `BG_DESKTOP=1` environment variable so the data directory resolves to the user’s application support folder. The provided `build_exe.bat` handles this automatically for Windows builds.
- **Desktop alerts:** Success, warning, and error alerts now auto-close in the packaged Windows app too, so they do not stay stuck on screen after normal actions.

## Recent Changes

### 2026-03-30 10:02:59 IST (+0530)
- Customer statement PDFs and old statement redirect routes now resolve customers only by exact id or exact phone.
- The statement engine no longer falls back to fuzzy name or company matching, so other customers' bills and payments do not get mixed into a selected customer statement.
- The regression tests now cover the leak case where another customer's phone contains the selected customer's id digits.

### 2026-03-29 22:19:17 IST (+0530)
- The shared transaction modal now keeps loaded bills inside a scrollable bill pane, so the save button stays easy to reach even for customers with many bills.
- Home now shows the normal success alert after recording a transaction from the modal, so staff get a clear confirmation there too.
- The cloud sync floating button was removed from the home page, and only the settings button stays there.

### 2026-03-29 22:09:32 IST (+0530)
- The shared add-transaction modal no longer shows the old invoice dropdown.
- Payment mode can now load the selected customer's bills on demand, show compact bill rows, and expand item details before saving.
- If you select bills in that modal, the amount now follows the selected outstanding totals and the app records one linked payment entry per selected bill.

### 2026-03-29 21:49:52 IST (+0530)
- Alerts now auto-close more reliably across the whole app, including the packaged Windows desktop build.
- The shared alert script no longer depends on Bootstrap's alert close helper, so bill-created and other page-level alerts now disappear on their own more consistently.
- The main page-level alerts now use the same dismissible alert pattern, and the desktop launcher now prefers the newer Windows webview when it is available.

### 2026-03-29 16:34:23 IST (+0530)
- Windows packaging is now one-step again.
- `build_exe.bat` now creates its own local `.build-venv`, installs dependencies and PyInstaller, and builds the `.exe` without requiring a manually prepared venv.
- The packaging docs now match the actual current Windows build flow and output file name.

### 2026-03-29 16:25:59 IST (+0530)
- The add-customer bill flow is now airtight: when you create a customer from the bill picker, the app takes you straight back into bill creation for that customer.
- Missing-customer routes now fail safely with redirects instead of falling into a 404 path.
- The customer picker now uses one safe alphabetical order from the server instead of re-sorting in the template.
- The old unused statement template leftovers were cleaned up.
- The `About Customer` and `Edit Customer` pages now match the newer card-based design language.
- The README now reflects the current customer flow and current company-statement entry wording.

### 2026-03-29 12:14:11 IST (+0530)
- The customer list page now uses the newer card-based design instead of the older table layout.
- The add-customer page now keeps only the useful preview panel and no longer shows the extra tips panel.

### 2026-03-29 12:09:22 IST (+0530)
- The `Add New Customer` page now uses the newer design style instead of the older centered form.
- The customer form now has a cleaner two-column layout, a live preview card, clearer helper notes, and a better back action when you come from the billing flow.

### 2026-03-29 12:03:06 IST (+0530)
- The `Draft Bills` page now has bulk delete actions.
- You can delete all active drafts at once, or delete all active drafts for one customer when that customer filter is open.

### 2026-03-29 11:57:50 IST (+0530)
- The app now has a full bill draft workflow.
- Drafts are stored separately from real invoices and only become real bills when `Generate Bill` is used.
- The create bill page now supports `Save Draft`, `Update Draft`, and `Delete Draft`.
- The home page now has a `Draft Bills` entry point.
- The customer picker now shows draft counts and an `Open Drafts` shortcut for customers with active drafts.
- The bill detail page now has `Duplicate as Draft`.
- Draft rows also keep delivery challan and rounded-line settings when they are reopened or duplicated from a real invoice.

### 2026-03-29 11:22:06 IST (+0530)
- The home page no longer shows the `Generate UPI QR` shortcut.
- The home page company-wide statement entry was simplified.
- The company statement page now has two modes: `Simple` and `Accounting Statement`.
- `Simple` is the default mode and shows only invoice rows with one total.
- `Accounting Statement` keeps the invoice list and the transaction ledger for the selected dates.
- The company statement page no longer has customer search or transaction-type filters. It now uses only the date filter.
- Customer accounting PDFs now use their own customer route, so the company statement page stays company-only.

### 2026-03-29 18:15:52 IST (+0530)
- The printed dues table heading can now be changed from Invoice Settings without changing the styling.
- The same dues heading setting works for both normal lower placement and the upper below-logo placement.

### 2026-03-29 11:30:54 IST (+0530)
- The home page labels are now shorter and clearer: `Client Statement` for customer accounting and `Company Books` for the company-wide numbers page.
- The customer accounting page now has a quick `Mark as Paid` button on each unpaid invoice.
- The company statement page now has the same quick `Mark as Paid` action in both `Simple` and `Accounting Statement` invoice lists.

### 2026-03-28 17:26:33 IST (+0530)
- The whole-company statement page is now much simpler.
- It now shows the date filter, compact totals, the invoice list for that period, and the transaction list, without the extra breakdown sections.
- The home page company-wide statement entry was shortened.

### 2026-03-28 17:20:33 IST (+0530)
- The app now treats accounting as the only statement flow.
- The whole-company statement now lives at `/accounting/statement`, and the customer `Simple Statement` now uses its own accounting-owned PDF route.
- The old statement pages are no longer used directly in the UI; they now only redirect into the accounting flow for compatibility.
- The home page now has separate customer/company accounting entry points, plus a direct `Add Transaction` button that opens the normal transaction modal.

### 2026-03-28 16:54:51 IST (+0530)
- The accounting PDF header now keeps just the logo and removes the extra repeated company name text.
- The simple statement PDF now uses slightly smaller `From` and `To` text so that section feels cleaner and less heavy.

### 2026-03-28 16:50:32 IST (+0530)
- The simple statement PDF logo was reduced so it no longer feels too large for the page.
- The logo now stays visible but more balanced with the rest of the simple statement layout.

### 2026-03-28 16:49:32 IST (+0530)
- The accounting PDF now uses the same company logo SVG style as the main bill preview.
- The logo size was kept balanced so it is clearly visible without taking over the page.

### 2026-03-28 16:47:29 IST (+0530)
- The customer accounting page now has `+` buttons beside bills and transactions.
- The bills `+` opens a new bill for that customer, and the transactions `+` opens the normal payment or expense modal with that customer already selected.
- The customer accounting PDF and the simple statement PDF now set clearer print titles, so saved PDF files use the company name and date more cleanly.

### 2026-03-28 16:38:51 IST (+0530)
- The customer accounting page now has a `Simple Statement` button.
- That button opens the older invoice-only PDF again, so you can print a simple customer statement with just bills and one total.
- The newer accounting PDF was kept as it is, so both print styles are now available from the same customer page.

### 2026-03-28 16:34:14 IST (+0530)
- The accounting statement builder now filters by the real customer id when a customer is selected, instead of doing a fuzzy name/company/phone match first.
- This fixes the missing-payment problem in the customer accounting PDF and related statement views when the print flow passed a customer id.
- The normal `/statements` date-wise statement flow was left as it was.

### 2026-03-28 16:31:36 IST (+0530)
- The main accounting dashboard now shows the full paid amount for each due customer instead of only counting payments tied to still-open invoices.
- This fixes the top due cards where `Paid` was showing `0` even though the customer had already made payments on older bills.

### 2026-03-28 16:29:35 IST (+0530)
- The customer statement page at `/statements_company` now reads the accounting ledger instead of showing only invoices.
- Payments received and balance due now update there correctly in the page as well as in CSV, XLSX, and PDF exports.
- The customer statement PDF now reuses the accounting statement print layout so the payment section stays in sync with recorded transactions.

### 2026-03-28 16:20:04 IST (+0530)
- The separate accounting statement page was removed from normal navigation and now the app uses the main accounting flow plus print/save PDF exports instead.
- The main accounting page now has a direct `Print / Save PDF` button for the whole company and no longer shows the extra quick note block.
- The top due customer cards were tightened to take less space, and customer search suggestions now fill the company name instead of the phone number.

### 2026-03-28 16:10:25 IST (+0530)
- The main `/accounting` page was simplified into a quick-read dashboard with a large customer search and only the top 3 due customers.
- A new customer accounting page now shows all-time dues, paid amount, compact bill history, expandable bill item details, collapsible transaction details, and a print/save PDF button.
- The customer page also has a hidden date filter so staff can narrow the view only when needed.

### 2026-03-28 15:44:06 IST (+0530)
- On the redesigned `View Bill` page, the customer bill list now scrolls inside the left panel instead of making the whole panel keep growing.
- The `Create New Bill` shortcuts now sit below that history list in the same left panel.
- The top `Edit`, `Delete`, and `Mark as Paid` actions were tightened so the page stays shorter and more compact.

### 2026-03-28 15:41:21 IST (+0530)
- On the redesigned `View Bill` page, the `Bill with Dues` and `Print Bill` buttons now sit back at the bottom of the page, below the items section.
- They were kept larger and easier to spot and click there.

### 2026-03-28 15:37:51 IST (+0530)
- The `View Bill` page now uses the newer two-column layout instead of the older centered table design.
- It now has a left-side customer bill list with the current bill highlighted, and clicking another bill opens that bill's detail page.
- The bill actions, customer details, items, and total were kept, but restyled to match the newer bills pages.

### 2026-03-28 15:27:22 IST (+0530)
- The extra `Total Due` line and `Hide Total` button were removed from the dues bill preview.
- The dues table and QR total stay the same.

### 2026-03-28 15:19:40 IST (+0530)
- The bill preview now shows `Hide Phone` as a normal action button beside `Hide UPI QR`.
- The old inline phone switch under the customer phone number was removed.

### 2026-03-28 12:46:00 IST (+0530)
- The UPI QR on the printed `Bill with Dues` page now encodes the same grand total that is shown on the page.
- Scanning the QR now asks for the full selected dues total instead of only the current invoice amount.

### 2026-03-28 12:43:29 IST (+0530)
- The printed `Bill with Dues` preview now uses tighter spacing between sections so it fits on one page more often without looking cramped.
- This spacing change only affects the dues preview layout and keeps the normal invoice preview style as it is.

### 2026-03-28 12:38:19 IST (+0530)
- The `All Past Dues` table on the printed bill now shows the total only once below the table.
- When the dues table is placed in the upper position, it now sits after the `From` and `To` section and before the `Tax Invoice` heading and invoice items.

### 2026-03-28 12:32:49 IST (+0530)
- The final `All Past Dues` total on the printed bill now shows the rupee symbol clearly.
- A new invoice setting now lets you place the `All Past Dues` table either below the logo or in the existing lower spot below the totals.

### 2026-03-28 12:26:44 IST (+0530)
- Bills on the `Bill with Dues` page now have a `Mark as Paid` action on the page itself.
- That action records a payment with a clear remark saying it was marked as paid from the Bill with Dues page.
- It now records only the remaining balance for that invoice, so partially paid bills do not get overpaid by mistake.

### 2026-03-28 12:20:33 IST (+0530)
- The `Bill with Dues` picker now shows the full bill list on the left and the customer summary and total on the right.
- The current bill now appears in that left list, starts selected, and can be cleared with `Unselect all`.
- The picker action now says `Print Bill with Dues`, and it disables itself when nothing is selected.
- The printed dues block now says `All Past Dues`, uses a stronger final total, and the QR amount follows that combined total when the dues block is shown.

### 2026-03-28 12:06:48 IST (+0530)
- The bill detail page now has a `Bill with Dues` button next to the normal print action.
- That button opens a new picker page where staff can select older unpaid bills for the same customer or use `Select all unpaid`.
- The printed A4 bill preview can now show one extra summary table with the current invoice plus the selected older dues and one final total.
- Older dues on that page use the remaining balance after recorded payments, not just the paid flag.

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
