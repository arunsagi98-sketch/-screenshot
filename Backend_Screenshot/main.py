"""
Creative Scanner Pro — FastAPI application factory.

Responsibilities of this file (and ONLY this file):
  - Create the FastAPI app instance
  - Register middleware
  - Mount static file directories
  - Include routers
  - Run the startup event (DB migration guard)

All business logic lives in routers/ and services/.
"""
import asyncio
import logging
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from core.config import get_settings
from core.logging import configure_logging
from core.paths import FRONTEND_DIR, get_paths
from database.db import engine
from routers import auth, creatives, crm, final_report, ppt_store, results, scan, screenshot_db, users, utilities

# ── Logging ───────────────────────────────────────────────────────────────────
configure_logging()
logger = logging.getLogger(__name__)

# ── Windows asyncio policy (Playwright requirement) ───────────────────────────
if sys.platform == "win32" and sys.version_info < (3, 14):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

settings = get_settings()

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Creative Scanner Pro",
    description="Ad detection, creative injection, and screenshot automation.",
    version="2.0.0",
)

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # Lock this to your domain in production
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)          # /auth/login, /auth/me
app.include_router(users.router)         # /users/ — super_admin only
app.include_router(scan.router)
app.include_router(results.router)
app.include_router(creatives.router)
app.include_router(ppt_store.router)
app.include_router(utilities.router)
app.include_router(crm.router)
app.include_router(final_report.router)
app.include_router(screenshot_db.router)

# ── Static directories ────────────────────────────────────────────────────────
paths = get_paths()
for folder in paths.values():
    os.makedirs(folder, exist_ok=True)

app.mount("/screenshots", StaticFiles(directory=paths["screenshots"]), name="screenshots")
app.mount("/creatives",   StaticFiles(directory=paths["input_images"]), name="creatives")
app.mount("/ppt-reports", StaticFiles(directory=paths["ppt_reports"]),  name="ppt_reports")


# ── Root redirect ─────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def home():
    if os.path.isfile(os.path.join(FRONTEND_DIR, "index.html")):
        return RedirectResponse(url="/ui/")
    return {"status": "online"}


# ── Startup — DB migration guard ──────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    logger.info("Starting Creative Scanner Pro [env=%s]", settings.app_env)

    from models.screenshot import Base
    import models.user  # noqa: F401 — registers User with Base
    Base.metadata.create_all(bind=engine)
    logger.info("scanner.db tables ready (incl. users)")

    # ── ctr_db: create scan_screenshots table if it doesn't exist ─────────────
    from database.crm_db import crm_engine, CrmBase
    import models.scan_screenshot  # noqa: F401 — registers ScanScreenshot with CrmBase
    CrmBase.metadata.create_all(bind=crm_engine)
    logger.info("ctr_db scan_screenshots table ready")

    # Column-level migration guard (safe to run repeatedly)
    # Replace this with Alembic once you adopt proper migrations.
    is_sqlite = settings.database_url.startswith("sqlite")
    new_cols = [
        ("matched_creative_name",    "VARCHAR"),
        ("matched_creative_size",    "VARCHAR"),
        ("injection_type",           "VARCHAR"),
        ("device",                   "VARCHAR DEFAULT 'Desktop'"),
        ("original_screenshot_path", "VARCHAR"),
    ]
    with engine.connect() as conn:
        for col, col_type in new_cols:
            try:
                stmt = (
                    f"ALTER TABLE screenshot_results ADD COLUMN {col} {col_type};"
                    if is_sqlite
                    else f"ALTER TABLE screenshot_results ADD COLUMN IF NOT EXISTS {col} {col_type};"
                )
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()
    logger.info("Startup migrations complete")

    # ── CRM DB column guard (ctr_db / processed_files) ───────────────────────
    from database.crm_db import crm_engine
    crm_is_sqlite = settings.crm_database_url.startswith("sqlite") if hasattr(settings, "crm_database_url") else False
    with crm_engine.connect() as conn:
        try:
            stmt = (
                "ALTER TABLE processed_files ADD COLUMN ad_type VARCHAR;"
                if crm_is_sqlite
                else "ALTER TABLE processed_files ADD COLUMN IF NOT EXISTS ad_type VARCHAR;"
            )
            conn.execute(text(stmt))
            conn.commit()
        except Exception:
            conn.rollback()
    logger.info("CRM DB column migrations complete")


# ── Frontend UI (served from /ui/) ────────────────────────────────────────────
if os.path.isfile(os.path.join(FRONTEND_DIR, "index.html")):
    app.mount("/ui", StaticFiles(directory=FRONTEND_DIR, html=True), name="ui")
    logger.info("Frontend UI mounted at /ui/")
