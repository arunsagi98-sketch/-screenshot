"""
Results router — GET/DELETE /results, POST /results/export-ppt
"""
import asyncio
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from core.auth import require_api_key
from schemas.results import ExportPPTRequest
from services.db_service import delete_screenshot_result, get_all_results
from services.ppt_exporter import generate_ppt_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/results", tags=["Results"])


@router.get("")
async def get_results(_: None = Depends(require_api_key)):
    """Return all scan results, newest first."""
    results = await asyncio.to_thread(get_all_results)
    return results


@router.delete("/{result_id}")
async def delete_result(result_id: int, _: None = Depends(require_api_key)):
    """Delete a single scan result by ID."""
    success = await asyncio.to_thread(delete_screenshot_result, result_id)
    if success:
        return {"status": "success", "deleted_id": result_id}
    return JSONResponse(status_code=404, content={"status": "error", "message": "Result not found"})


@router.post("/export-ppt")
async def export_ppt(body: ExportPPTRequest, _: None = Depends(require_api_key)):
    """Generate a PPTX report for the given result IDs and stream it back."""
    if not body.ids:
        return JSONResponse(status_code=400, content={"status": "error", "message": "No IDs provided"})
    try:
        ppt_buffer = await asyncio.to_thread(generate_ppt_report, body.ids)
    except Exception:
        logger.exception("PPT generation failed")
        return JSONResponse(status_code=500, content={"status": "error", "message": "PPT generation failed"})
    if not ppt_buffer:
        return JSONResponse(status_code=404, content={"status": "error", "message": "No records found"})
    ppt_buffer.seek(0)
    return StreamingResponse(
        ppt_buffer,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": "attachment; filename=campaign_report.pptx"},
    )
