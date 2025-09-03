# migration.py

import sqlite3
import os

def migrate_db(db_path):
    if not os.path.exists(db_path):
        print(f"[Migration] Database '{db_path}' not found. Skipping.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    required_columns = {
        'exclude_phone': "ALTER TABLE invoice ADD COLUMN exclude_phone BOOLEAN DEFAULT 0",
        'exclude_gst': "ALTER TABLE invoice ADD COLUMN exclude_gst BOOLEAN DEFAULT 0",
        'exclude_addr': "ALTER TABLE invoice ADD COLUMN exclude_addr BOOLEAN DEFAULT 0"
    }

    try:
        cursor.execute("PRAGMA table_info(invoice);")
        existing_cols = [col[1] for col in cursor.fetchall()]

        for col, sql in required_columns.items():
            if col not in existing_cols:
                print(f"[Migration] Adding missing column: {col}")
                cursor.execute(sql)

        conn.commit()
        print("[Migration] DB schema is up-to-date.")
    except Exception as e:
        print(f"[Migration ERROR] {e}")
    finally:
        conn.close()