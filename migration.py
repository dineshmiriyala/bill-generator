# migration.py

import sqlite3
import os

def migrate_db(db_path):
    if not os.path.exists(db_path):
        print(f"[Migration] Database '{db_path}' not found. Skipping.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='last_backup';")
        table_exists = cursor.fetchone()

        if not table_exists:
            print("[Migration] Creating missing table: last_backup")
            cursor.execute("""
                CREATE TABLE last_backup (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    note TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='layout_config';")
        layout_table_exists = cursor.fetchone()

        if not layout_table_exists:
            print("[Migration] Creating missing table: layout_config")
            cursor.execute("""
                CREATE TABLE layout_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sizes_json TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='accounting_transaction';")
        accounting_table_exists = cursor.fetchone()

        if not accounting_table_exists:
            print("[Migration] Creating missing table: accounting_transaction")
            cursor.execute("""
                CREATE TABLE accounting_transaction (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    txn_id TEXT NOT NULL UNIQUE,
                    customerId INTEGER,
                    amount REAL NOT NULL,
                    txn_type TEXT NOT NULL DEFAULT 'income',
                    mode TEXT,
                    account TEXT,
                    invoice_no TEXT,
                    remarks TEXT,
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(customerId) REFERENCES customer(id)
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS ix_accounting_transaction_customerId ON accounting_transaction(customerId);")
            cursor.execute("CREATE INDEX IF NOT EXISTS ix_accounting_transaction_invoice_no ON accounting_transaction(invoice_no);")
            cursor.execute("CREATE INDEX IF NOT EXISTS ix_accounting_transaction_txn_type ON accounting_transaction(txn_type);")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='expense_item';")
        expense_table_exists = cursor.fetchone()

        if not expense_table_exists:
            print("[Migration] Creating missing table: expense_item")
            cursor.execute("""
                CREATE TABLE expense_item (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transactionId INTEGER NOT NULL,
                    description TEXT,
                    amount REAL,
                    FOREIGN KEY(transactionId) REFERENCES accounting_transaction(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS ix_expense_item_transactionId ON expense_item(transactionId);")

        conn.commit()
        print("[Migration] DB schema is up-to-date.")
    except Exception as e:
        print(f"[Migration ERROR] {e}")
    finally:
        conn.close()
