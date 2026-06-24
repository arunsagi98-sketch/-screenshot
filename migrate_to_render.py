"""
migrate_to_render.py
====================
Migrates app_url_reference and city_reference from local ctr_db → Render ctr_db.

Run:
    python migrate_to_render.py
"""
import sys
import psycopg2
from psycopg2.extras import execute_values

LOCAL_URL  = "postgresql://postgres:Arun%40123%24@localhost:5432/ctr_db"
RENDER_URL = "postgresql://ctr_db_user:PsSZYSwg0APjrwyI34Sg8hHxaKYyi1M4@dpg-d8ta4q37uimc73dk0vg0-a.oregon-postgres.render.com/ctr_db"

def migrate_table(local_cur, render_cur, render_conn, table, columns, create_sql):
    print(f"\n--- {table} ---")
    # Create table on Render
    render_cur.execute(create_sql)
    render_conn.commit()

    # Count local rows
    local_cur.execute(f"SELECT COUNT(*) FROM {table}")
    count = local_cur.fetchone()[0]
    if count == 0:
        print(f"  [skip] No rows in local {table}")
        return

    # Truncate Render table
    render_cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY;")
    render_conn.commit()

    # Fetch all local rows
    local_cur.execute(f"SELECT {', '.join(columns)} FROM {table}")
    rows = local_cur.fetchall()

    # Insert to Render
    placeholders = ", ".join(["%s"] * len(columns))
    execute_values(
        render_cur,
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s",
        rows,
        page_size=500,
    )
    render_conn.commit()
    print(f"  Inserted {len(rows)} rows into Render {table}")


def run():
    print("Connecting to local ctr_db...")
    local_conn = psycopg2.connect(LOCAL_URL)
    local_cur  = local_conn.cursor()

    print("Connecting to Render ctr_db...")
    render_conn = psycopg2.connect(RENDER_URL)
    render_cur  = render_conn.cursor()

    # ── app_url_reference ──────────────────────────────────────────────────
    migrate_table(
        local_cur, render_cur, render_conn,
        table   = "app_url_reference",
        columns = ["sheet_name", "url_id", "url", "priority"],
        create_sql = """
            CREATE TABLE IF NOT EXISTS app_url_reference (
                id          SERIAL PRIMARY KEY,
                sheet_name  VARCHAR(200) NOT NULL,
                url_id      INTEGER,
                url         VARCHAR(1000) NOT NULL,
                priority    VARCHAR(20)  NOT NULL DEFAULT 'regular'
            );
            CREATE INDEX IF NOT EXISTS idx_app_url_sheet    ON app_url_reference (sheet_name);
            CREATE INDEX IF NOT EXISTS idx_app_url_priority ON app_url_reference (sheet_name, priority);
        """,
    )

    # ── city_reference ─────────────────────────────────────────────────────
    try:
        local_cur.execute("SELECT COUNT(*) FROM city_reference")
        migrate_table(
            local_cur, render_cur, render_conn,
            table   = "city_reference",
            columns = ["sheet_name", "city_name", "potential_impressions", "unique_cookies"],
            create_sql = """
                CREATE TABLE IF NOT EXISTS city_reference (
                    id                    SERIAL PRIMARY KEY,
                    sheet_name            VARCHAR(200) NOT NULL,
                    city_name             VARCHAR(200),
                    potential_impressions BIGINT,
                    unique_cookies        BIGINT
                );
                CREATE INDEX IF NOT EXISTS idx_city_sheet ON city_reference (sheet_name);
            """,
        )
    except Exception as e:
        print(f"  [skip] city_reference not found locally: {e}")
        local_conn.rollback()

    local_cur.close();  local_conn.close()
    render_cur.close(); render_conn.close()
    print("\nMigration complete!")


if __name__ == "__main__":
    run()
