import bcrypt, psycopg2, json

RAILWAY_URL = "postgresql://postgres:imGiWkhxTvTjtEGvcgyaPUKpJVrrDWjP@zephyr.proxy.rlwy.net:45185/railway"

users_to_create = [
    ("report_user", "Pass@123", "admin", ["final_report"]),
]

conn = psycopg2.connect(RAILWAY_URL)
cur  = conn.cursor()

for username, password, role, pages in users_to_create:
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    cur.execute("""
        INSERT INTO users (username, hashed_password, role, allowed_pages, is_active)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (username) DO NOTHING
    """, (username, hashed, role, json.dumps(pages), True))
    print(f"  ✅ {username} created (role={role}, pages={pages})")

conn.commit()
cur.close()
conn.close()
print("Done!")
