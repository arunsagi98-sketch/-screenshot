"""
migrate_users_to_railway.py
============================
Copies all users from local ctr_db → Railway DB.
Run: python migrate_users_to_railway.py
"""
import psycopg2
import json

LOCAL_URL   = "postgresql://postgres:Arun%40123%24@localhost:5432/ctr_db"
RAILWAY_URL = "postgresql://postgres:imGiWkhxTvTjtEGvcgyaPUKpJVrrDWjP@zephyr.proxy.rlwy.net:45185/railway"

print("Connecting to local ctr_db...")
local_conn = psycopg2.connect(LOCAL_URL)
local_cur  = local_conn.cursor()

print("Connecting to Railway DB...")
rail_conn  = psycopg2.connect(RAILWAY_URL)
rail_cur   = rail_conn.cursor()

# Fetch all local users
local_cur.execute("SELECT username, email, hashed_password, role, allowed_pages, is_active FROM users")
users = local_cur.fetchall()
print(f"Found {len(users)} users in local DB")

# Insert into Railway (skip if already exists)
for row in users:
    username, email, hashed_password, role, allowed_pages, is_active = row
    pages_json = json.dumps(allowed_pages) if allowed_pages is not None else None
    rail_cur.execute("""
        INSERT INTO users (username, email, hashed_password, role, allowed_pages, is_active)
        VALUES (%s, %s, %s, %s, %s::json, %s)
        ON CONFLICT (username) DO UPDATE SET
            email           = EXCLUDED.email,
            hashed_password = EXCLUDED.hashed_password,
            role            = EXCLUDED.role,
            allowed_pages   = EXCLUDED.allowed_pages,
            is_active       = EXCLUDED.is_active
    """, (username, email, hashed_password, role, pages_json, is_active))
    print(f"  ✅ {username} (role={role}, pages={allowed_pages})")

rail_conn.commit()
local_cur.close(); local_conn.close()
rail_cur.close();  rail_conn.close()

print(f"\nDone! {len(users)} users migrated to Railway DB.")
