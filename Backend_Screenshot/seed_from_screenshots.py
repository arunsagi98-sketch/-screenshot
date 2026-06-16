"""
Standalone seed script — uses only built-in sqlite3, no app imports.
Run once: cd Backend_Screenshot && python seed_from_screenshots.py
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "scanner.db")
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Create table if missing
cur.execute("""
CREATE TABLE IF NOT EXISTS screenshot_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT,
    screenshot_path TEXT,
    original_screenshot_path TEXT,
    status TEXT,
    ads_found INTEGER DEFAULT 0,
    matches_found INTEGER DEFAULT 0,
    matched_creative_name TEXT,
    matched_creative_size TEXT,
    injection_type TEXT,
    device TEXT DEFAULT 'Desktop',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

count_before = cur.execute("SELECT COUNT(*) FROM screenshot_results").fetchone()[0]
print(f"Existing records: {count_before}")

seeded = 0
for fname in sorted(os.listdir(SCREENSHOTS_DIR)):
    if not fname.lower().endswith(".png"):
        continue
    path = f"screenshots/{fname}"
    exists = cur.execute(
        "SELECT 1 FROM screenshot_results WHERE screenshot_path=?", (path,)
    ).fetchone()
    if exists:
        continue
    domain = fname.replace(".png", "").replace("_", ".")
    cur.execute("""
        INSERT INTO screenshot_results
            (url, screenshot_path, status, ads_found, matches_found, device, created_at)
        VALUES (?, ?, 'success', 1, 1, 'Desktop', ?)
    """, (f"https://{domain}", path, datetime.utcnow().isoformat()))
    seeded += 1

conn.commit()
total = cur.execute("SELECT COUNT(*) FROM screenshot_results").fetchone()[0]
conn.close()

print(f"Seeded {seeded} new records. Total in DB: {total}")
print("Done! Refresh the browser to see results.")
