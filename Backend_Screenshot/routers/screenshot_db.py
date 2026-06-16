"""
/db-screenshots  — API for screenshot images stored in ctr_db.

Endpoints
---------
GET  /db-screenshots/                   list metadata (paginated, filterable)
GET  /db-screenshots/{id}/image         serve injected screenshot as image/png
GET  /db-screenshots/{id}/original      serve original screenshot as image/png
GET  /db-screenshots/{id}               single record metadata
DELETE /db-screenshots/{id}             remove record + images from DB
POST /db-screenshots/save               manually push a result into the DB
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from services.screenshot_storage import (
    delete_screenshot,
    get_original_bytes,
    get_screenshot_bytes,
    list_screenshots,
    save_screenshot_to_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/db-screenshots", tags=["Screenshot DB"])


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("/", summary="List screenshot records (no binary data)")
def list_db_screenshots(
    scan_job_id: Optional[str] = Query(None, description="Filter by scan job UUID"),
    domain:      Optional[str] = Query(None, description="Filter by domain (partial match)"),
    status:      Optional[str] = Query(None, description="Filter by status: success/skipped/failed"),
    limit:       int           = Query(50,   ge=1, le=500),
    offset:      int           = Query(0,    ge=0),
):
    """
    Returns metadata for all stored screenshots.
    Each record includes `image_url` and `original_url` fields the
    frontend can use as `<img src="...">` values.
    """
    rows = list_screenshots(
        scan_job_id=scan_job_id,
        domain=domain,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"count": len(rows), "results": rows}


# ── Single record metadata ────────────────────────────────────────────────────

@router.get("/{record_id}", summary="Get single record metadata")
def get_db_screenshot_meta(record_id: int):
    rows = list_screenshots(limit=1, offset=0)   # cheap way to reuse _to_meta
    # Use storage service directly
    from database.crm_db import CrmSessionLocal
    from models.scan_screenshot import ScanScreenshot
    db  = CrmSessionLocal()
    try:
        row = db.query(ScanScreenshot).filter(ScanScreenshot.id == record_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Record not found")
        from services.screenshot_storage import _to_meta
        return _to_meta(row)
    finally:
        db.close()


# ── Image serving ─────────────────────────────────────────────────────────────

@router.get("/{record_id}/image", summary="Serve injected screenshot as image")
def serve_screenshot_image(record_id: int):
    """
    Returns the injected (after) screenshot binary.
    Frontend usage: <img src="/db-screenshots/42/image" />
    """
    result = get_screenshot_bytes(record_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Screenshot not found in DB")
    image_bytes, mime_type = result
    return Response(
        content=image_bytes,
        media_type=mime_type,
        headers={"Cache-Control": "max-age=3600"},
    )


@router.get("/{record_id}/original", summary="Serve original (before) screenshot as image")
def serve_original_image(record_id: int):
    """
    Returns the original (before injection) screenshot binary.
    Frontend usage: <img src="/db-screenshots/42/original" />
    """
    result = get_original_bytes(record_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Original screenshot not found in DB")
    image_bytes, mime_type = result
    return Response(
        content=image_bytes,
        media_type=mime_type,
        headers={"Cache-Control": "max-age=3600"},
    )


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{record_id}", summary="Delete a screenshot record")
def delete_db_screenshot(record_id: int):
    deleted = delete_screenshot(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"deleted": True, "id": record_id}


# ── Manual save ───────────────────────────────────────────────────────────────

class SaveRequest(BaseModel):
    url:             str
    domain:          str            = ""
    device:          str            = "Desktop"
    status:          str            = "success"
    screenshot_path: Optional[str] = None
    original_path:   Optional[str] = None
    scan_job_id:     Optional[str] = None
    ads_found:       int           = 0
    slots_injected:  int           = 0
    creative_name:   Optional[str] = None
    creative_size:   Optional[str] = None
    injection_type:  Optional[str] = None
    match_score:     Optional[float] = None
    notes:           Optional[str] = None


@router.post("/save", summary="Save a scan result + screenshots to DB")
def save_db_screenshot(body: SaveRequest):
    """
    Reads the PNG files from `screenshot_path` / `original_path` on disk
    and persists them to ctr_db.  Called automatically by the scan engine
    after each successful injection; can also be called manually.
    """
    row = save_screenshot_to_db(**body.model_dump())
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to save screenshot to DB")
    from services.screenshot_storage import _to_meta
    return {"saved": True, "record": _to_meta(row)}
