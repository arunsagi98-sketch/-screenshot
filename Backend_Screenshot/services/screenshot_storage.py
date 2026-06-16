"""
CRUD helpers for scan_screenshots in ctr_db.

Public API
----------
save_screenshot_to_db()   — read PNG files from disk, write row to ctr_db
get_screenshot_bytes()    — return raw bytes for the injected screenshot
get_original_bytes()      — return raw bytes for the original screenshot
list_screenshots()        — paginated metadata list (no binary)
delete_screenshot()       — remove a row by id
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from database.crm_db import CrmSessionLocal
from models.scan_screenshot import ScanScreenshot

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _read_file(path: Optional[str]) -> Optional[bytes]:
    """Read a file from disk; return None if path is blank or file missing."""
    if not path:
        return None
    # Resolve relative paths from the Backend_Screenshot directory
    if not os.path.isabs(path):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, path)
    if not os.path.isfile(path):
        logger.debug("[SCREENSHOT-DB] File not found: %s", path)
        return None
    with open(path, "rb") as f:
        return f.read()


def _to_meta(row: ScanScreenshot) -> dict:
    """Serialize a row without binary data (safe for JSON responses)."""
    return {
        "id":             row.id,
        "scan_job_id":    row.scan_job_id,
        "url":            row.url,
        "domain":         row.domain,
        "device":         row.device,
        "status":         row.status,
        "ads_found":      row.ads_found,
        "slots_injected": row.slots_injected,
        "creative_name":  row.creative_name,
        "creative_size":  row.creative_size,
        "injection_type": row.injection_type,
        "match_score":    row.match_score,
        "notes":          row.notes,
        "mime_type":      row.mime_type,
        "file_size_kb":   row.file_size_kb,
        "has_screenshot": row.screenshot_data is not None,
        "has_original":   row.original_data   is not None,
        "captured_at":    row.captured_at.isoformat() if row.captured_at else None,
        # Convenience URLs for the frontend
        "image_url":      f"/db-screenshots/{row.id}/image"    if row.screenshot_data else None,
        "original_url":   f"/db-screenshots/{row.id}/original" if row.original_data   else None,
    }


# ── public CRUD ───────────────────────────────────────────────────────────────

def save_screenshot_to_db(
    *,
    url:             str,
    domain:          str                   = "",
    device:          str                   = "Desktop",
    status:          str                   = "success",
    screenshot_path: Optional[str]         = None,
    original_path:   Optional[str]         = None,
    scan_job_id:     Optional[str]         = None,
    ads_found:       int                   = 0,
    slots_injected:  int                   = 0,
    creative_name:   Optional[str]         = None,
    creative_size:   Optional[str]         = None,
    injection_type:  Optional[str]         = None,
    match_score:     Optional[float]       = None,
    notes:           Optional[str]         = None,
    db:              Optional[Session]     = None,
) -> Optional[ScanScreenshot]:
    """
    Read PNG files from disk and persist them to ctr_db.
    Returns the saved ORM row, or None on failure.
    """
    screenshot_bytes = _read_file(screenshot_path)
    original_bytes   = _read_file(original_path)

    file_size_kb = len(screenshot_bytes) // 1024 if screenshot_bytes else None

    _own = db is None
    db   = db or CrmSessionLocal()
    try:
        row = ScanScreenshot(
            scan_job_id    = scan_job_id,
            url            = url,
            domain         = domain,
            device         = device,
            status         = status,
            ads_found      = ads_found,
            slots_injected = slots_injected,
            creative_name  = creative_name,
            creative_size  = creative_size,
            injection_type = injection_type,
            match_score    = match_score,
            notes          = notes,
            screenshot_data= screenshot_bytes,
            original_data  = original_bytes,
            mime_type      = "image/png",
            file_size_kb   = file_size_kb,
            captured_at    = datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info(
            "[SCREENSHOT-DB] Saved id=%s url=%s status=%s size=%sKB",
            row.id, url, status, file_size_kb,
        )
        return row
    except Exception:
        db.rollback()
        logger.exception("[SCREENSHOT-DB] Failed to save for url=%s", url)
        return None
    finally:
        if _own:
            db.close()


def get_screenshot_bytes(
    record_id: int,
    db: Optional[Session] = None,
) -> Optional[tuple[bytes, str]]:
    """Return (image_bytes, mime_type) for the injected screenshot, or None."""
    _own = db is None
    db   = db or CrmSessionLocal()
    try:
        row = db.query(ScanScreenshot).filter(ScanScreenshot.id == record_id).first()
        if row and row.screenshot_data:
            return row.screenshot_data, row.mime_type or "image/png"
        return None
    finally:
        if _own:
            db.close()


def get_original_bytes(
    record_id: int,
    db: Optional[Session] = None,
) -> Optional[tuple[bytes, str]]:
    """Return (image_bytes, mime_type) for the original screenshot, or None."""
    _own = db is None
    db   = db or CrmSessionLocal()
    try:
        row = db.query(ScanScreenshot).filter(ScanScreenshot.id == record_id).first()
        if row and row.original_data:
            return row.original_data, row.mime_type or "image/png"
        return None
    finally:
        if _own:
            db.close()


def list_screenshots(
    *,
    scan_job_id: Optional[str]     = None,
    domain:      Optional[str]     = None,
    status:      Optional[str]     = None,
    limit:       int               = 50,
    offset:      int               = 0,
    db:          Optional[Session] = None,
) -> list[dict]:
    """Return metadata rows (no binary) ordered newest-first."""
    _own = db is None
    db   = db or CrmSessionLocal()
    try:
        q = db.query(ScanScreenshot)
        if scan_job_id:
            q = q.filter(ScanScreenshot.scan_job_id == scan_job_id)
        if domain:
            q = q.filter(ScanScreenshot.domain.ilike(f"%{domain}%"))
        if status:
            q = q.filter(ScanScreenshot.status == status)
        rows = (
            q.order_by(ScanScreenshot.captured_at.desc())
             .offset(offset)
             .limit(limit)
             .all()
        )
        return [_to_meta(r) for r in rows]
    finally:
        if _own:
            db.close()


def delete_screenshot(
    record_id: int,
    db: Optional[Session] = None,
) -> bool:
    """Delete a record by id. Returns True if deleted, False if not found."""
    _own = db is None
    db   = db or CrmSessionLocal()
    try:
        row = db.query(ScanScreenshot).filter(ScanScreenshot.id == record_id).first()
        if not row:
            return False
        db.delete(row)
        db.commit()
        logger.info("[SCREENSHOT-DB] Deleted id=%s", record_id)
        return True
    except Exception:
        db.rollback()
        logger.exception("[SCREENSHOT-DB] Failed to delete id=%s", record_id)
        return False
    finally:
        if _own:
            db.close()
