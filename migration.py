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

        conn.commit()
        print("[Migration] DB schema is up-to-date.")
    except Exception as e:
        print(f"[Migration ERROR] {e}")
    finally:
        conn.close()