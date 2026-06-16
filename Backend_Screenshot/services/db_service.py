"""
Database CRUD helpers for ScreenshotResult.

Each function accepts an optional `db` session so they can be called both:
  - from FastAPI endpoints via Depends(get_db)
  - from background tasks that manage their own session
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from database.db import SessionLocal
from models.screenshot import ScreenshotResult

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def _to_dict(r: ScreenshotResult) -> dict:
    """Serialise a ScreenshotResult ORM row to a plain dict."""
    created_utc = r.created_at.replace(tzinfo=timezone.utc) if r.created_at else None
    return {
        "id": r.id,
        "url": r.url,
        "screenshot_path": r.screenshot_path,
        "original_screenshot_path": r.original_screenshot_path,
        "status": r.status,
        "ads_found": r.ads_found,
        "matches_found": r.matches_found,
        "matched_creative_name": r.matched_creative_name,
        "matched_creative_size": r.matched_creative_size,
        "injection_type": r.injection_type,
        "device": r.device,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "created_at_ist": created_utc.astimezone(IST).isoformat() if created_utc else None,
    }


def save_screenshot_result(
    website: str,
    image_path: str,
    status: str,
    ads_found: int = 0,
    matches_found: int = 0,
    matched_creative_name: Optional[str] = None,
    matched_creative_size: Optional[str] = None,
    injection_type: Optional[str] = None,
    device: str = "Desktop",
    original_image_path: Optional[str] = None,
    db: Optional[Session] = None,
) -> ScreenshotResult:
    """Persist a scan result. Creates its own session if one is not provided."""
    _own_session = db is None
    db = db or SessionLocal()
    try:
        row = ScreenshotResult(
            url=website,
            screenshot_path=image_path,
            original_screenshot_path=original_image_path,
            status=status,
            ads_found=ads_found,
            matches_found=matches_found,
            matched_creative_name=matched_creative_name,
            matched_creative_size=matched_creative_size,
            injection_type=injection_type,
            device=device,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info("Saved result id=%s url=%s status=%s", row.id, website, status)
        return row
    except Exception:
        db.rollback()
        logger.exception("Failed to save result for url=%s", website)
        raise
    finally:
        if _own_session:
            db.close()


def get_all_results(db: Optional[Session] = None) -> list[dict]:
    """Return all results ordered newest-first."""
    _own_session = db is None
    db = db or SessionLocal()
    try:
        rows = db.query(ScreenshotResult).order_by(ScreenshotResult.created_at.desc()).all()
        return [_to_dict(r) for r in rows]
    finally:
        if _own_session:
            db.close()


def get_results_by_ids(ids: list[int], db: Optional[Session] = None) -> list:
    """Fetch specific rows by primary key list."""
    _own_session = db is None
    db = db or SessionLocal()
    try:
        return db.query(ScreenshotResult).filter(ScreenshotResult.id.in_(ids)).all()
    finally:
        if _own_session:
            db.close()


def delete_screenshot_result(result_id: int, db: Optional[Session] = None) -> bool:
    """Delete a result by ID. Returns True if deleted, False if not found."""
    _own_session = db is None
    db = db or SessionLocal()
    try:
        row = db.query(ScreenshotResult).filter(ScreenshotResult.id == result_id).first()
        if not row:
            return False
        db.delete(row)
        db.commit()
        logger.info("Deleted result id=%s", result_id)
        return True
    except Exception:
        db.rollback()
        logger.exception("Failed to delete result id=%s", result_id)
        return False
    finally:
        if _own_session:
            db.close()
