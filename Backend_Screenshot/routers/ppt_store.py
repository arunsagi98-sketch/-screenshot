"""
PPT Store router — template management + saved report library.

Endpoints
---------
GET  /ppt-store/templates           list uploaded templates
POST /ppt-store/templates/upload    upload a new template
DEL  /ppt-store/templates/{name}    delete a template
POST /ppt-store/export              generate & save a report
GET  /ppt-store/reports             list saved reports
DEL  /ppt-store/reports/{name}      delete a saved report
"""
import asyncio
import datetime
import logging
import os
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from core.auth import require_api_key
from core.paths import get_paths

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ppt-store", tags=["PPT Store"])


def _dirs() -> tuple[str, str]:
    paths = get_paths()
    return paths["ppt_format"], paths["ppt_reports"]


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/templates")
def list_ppt_templates(_: None = Depends(require_api_key)):
    """List all uploaded PPTX templates."""
    ppt_format_dir, _ = _dirs()
    files = [
        {
            "name": fname,
            "size_kb": round(os.path.getsize(os.path.join(ppt_format_dir, fname)) / 1024, 1),
            "modified": os.path.getmtime(os.path.join(ppt_format_dir, fname)),
        }
        for fname in os.listdir(ppt_format_dir)
        if fname.lower().endswith(".pptx")
    ]
    files.sort(key=lambda x: x["modified"], reverse=True)
    return {"templates": files}


@router.post("/templates/upload")
async def upload_ppt_template(request: Request, _: None = Depends(require_api_key)):
    """Upload a new PPTX template."""
    ppt_format_dir, _ = _dirs()
    try:
        form = await request.form()
    except Exception:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid form"})

    upload_files = [v for v in form.values() if hasattr(v, "filename") and v.filename]
    if not upload_files:
        return JSONResponse(status_code=400, content={"status": "error", "message": "No file received"})

    saved = []
    for f in upload_files:
        if not f.filename.lower().endswith(".pptx"):
            continue
        dest    = os.path.join(ppt_format_dir, os.path.basename(f.filename))
        content = await f.read()
        with open(dest, "wb") as fh:
            fh.write(content)
        saved.append(f.filename)

    if not saved:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Only .pptx files accepted"})
    return {"status": "ok", "saved": saved}


@router.delete("/templates/{filename}")
def delete_ppt_template(filename: str, _: None = Depends(require_api_key)):
    """Delete a PPTX template by filename."""
    ppt_format_dir, _ = _dirs()
    safe  = os.path.basename(filename)
    fpath = os.path.join(ppt_format_dir, safe)
    if not os.path.isfile(fpath):
        return JSONResponse(status_code=404, content={"status": "error", "message": "Template not found"})
    os.remove(fpath)
    return {"status": "ok", "deleted": safe}


# ── Export ────────────────────────────────────────────────────────────────────

@router.post("/export")
async def ppt_store_export(data: dict, _: None = Depends(require_api_key)):
    """
    Generate a PPTX from a chosen template + result IDs,
    save it to ppt_reports/ and return its download URL.
    """
    import services.ppt_exporter as _exp
    from services.ppt_exporter import generate_ppt_report

    ppt_format_dir, ppt_reports_dir = _dirs()

    ids           = [int(i) for i in data.get("ids", [])]
    template_name = data.get("template", "")
    report_title  = (data.get("title", "") or "campaign_report").strip()

    # Temporarily override the template inside the exporter
    _orig = _exp.TEMPLATE_NAME
    if template_name:
        safe_tname = os.path.basename(template_name)
        if os.path.isfile(os.path.join(ppt_format_dir, safe_tname)):
            _exp.TEMPLATE_NAME = safe_tname

    try:
        buf = await asyncio.to_thread(generate_ppt_report, ids if ids else None)
    except Exception:
        logger.exception("PPT Store export failed")
        return JSONResponse(status_code=500, content={"status": "error", "message": "PPT generation failed"})
    finally:
        _exp.TEMPLATE_NAME = _orig  # always restore

    if not buf:
        return JSONResponse(status_code=404, content={"status": "error", "message": "No records found"})

    ts         = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_title = re.sub(r"[^\w\-]", "_", report_title)[:40]
    filename   = f"{safe_title}_{ts}.pptx"
    dest_path  = os.path.join(ppt_reports_dir, filename)
    with open(dest_path, "wb") as fh:
        fh.write(buf.getvalue())

    return {
        "status": "ok",
        "filename": filename,
        "download_url": f"/ppt-reports/{filename}",
        "size_kb": round(os.path.getsize(dest_path) / 1024, 1),
    }


# ── Reports ───────────────────────────────────────────────────────────────────

@router.get("/reports")
def list_ppt_reports(_: None = Depends(require_api_key)):
    """List all saved PPTX reports."""
    _, ppt_reports_dir = _dirs()
    files = [
        {
            "name": fname,
            "size_kb": round(os.path.getsize(os.path.join(ppt_reports_dir, fname)) / 1024, 1),
            "modified": os.path.getmtime(os.path.join(ppt_reports_dir, fname)),
            "download_url": f"/ppt-reports/{fname}",
        }
        for fname in os.listdir(ppt_reports_dir)
        if fname.lower().endswith(".pptx")
    ]
    files.sort(key=lambda x: x["modified"], reverse=True)
    return {"reports": files}


@router.delete("/reports/{filename}")
def delete_ppt_report(filename: str, _: None = Depends(require_api_key)):
    """Delete a saved PPTX report by filename."""
    _, ppt_reports_dir = _dirs()
    safe  = os.path.basename(filename)
    fpath = os.path.join(ppt_reports_dir, safe)
    if not os.path.isfile(fpath):
        return JSONResponse(status_code=404, content={"status": "error", "message": "Report not found"})
    os.remove(fpath)
    return {"status": "ok", "deleted": safe}
