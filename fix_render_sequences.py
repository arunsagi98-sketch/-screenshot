"""
fix_render_sequences.py
=======================
Fixes missing SERIAL sequences on Render ctr_db tables.
Run: python fix_render_sequences.py
"""
import psycopg2

RENDER_URL = "postgresql://ctr_db_user:PsSZYSwg0APjrwyI34Sg8hHxaKYyi1M4@dpg-d8ta4q37uimc73dk0vg0-a.oregon-postgres.render.com/ctr_db"

TABLES = ["campaign_rules", "global_settings", "processed_files", "users", "scan_screenshots", "final_report_store"]

conn = psycopg2.connect(RENDER_URL)
cur  = conn.cursor()

for table in TABLES:
    seq = f"{table}_id_seq"
    try:
        cur.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq};")
        cur.execute(f"ALTER TABLE {table} ALTER COLUMN id SET DEFAULT nextval('{seq}');")
        cur.execute(f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false);")
        conn.commit()
        print(f"  Fixed: {table}")
    except Exception as e:
        conn.rollback()
        print(f"  Skip {table}: {e}")

cur.close()
conn.close()
print("\nDone!")
