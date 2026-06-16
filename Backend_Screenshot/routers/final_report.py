"""
Final Report router
===================
POST /final-report/process
  Accepts: multipart/form-data  →  file (.xlsx / .xls)
  Returns: JSON list of processed files
    [{"name": str, "filename": str, "ad_type": "Video"|"Banner"}, ...]

GET /final-report/download/{filename}
  Returns: individual .xlsx file

GET /final-report/languages
  Returns: list of distinct sheet_name values from app_url_reference

GET /final-report/cities
  Returns: list of distinct sheet_name values from city_reference
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from database.crm_db import crm_engine
from services.excel_splitter import split_excel_to_files
from services.report_generator import generate_report

def _get_ctr_conn():
    """Return a raw DBAPI connection from the shared crm_engine (no hardcoded creds)."""
    return crm_engine.raw_connection()

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/final-report", tags=["final-report"])

_FINAL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "final_report_outputs",
)
os.makedirs(_FINAL_DIR, exist_ok=True)


def _ensure_report_store():
    """Create final_report_store table if it doesn't exist."""
    try:
        conn = _get_ctr_conn()
        cur  = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS final_report_store (
                id              SERIAL PRIMARY KEY,
                campaign_name   TEXT,
                report_filename TEXT NOT NULL,
                generated_at    TIMESTAMPTZ DEFAULT NOW(),
                file_data       BYTEA NOT NULL
            )
        """)
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        logger.warning("_ensure_report_store failed: %s", e)

_ensure_report_store()


def _save_report_to_db(campaign_name: str, report_filename: str, file_data: bytes) -> int:
    """Insert report into DB, return new row id."""
    conn = _get_ctr_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        INSERT INTO final_report_store (campaign_name, report_filename, file_data)
        VALUES (%s, %s, %s) RETURNING id
        """,
        (campaign_name, report_filename, file_data),
    )
    row_id = cur.fetchone()[0]
    conn.commit()
    cur.close(); conn.close()
    return row_id

# Video detection keywords (for name-based fallback)
_VIDEO_KW = {"video", "vid", "15s", "30s", "6s", "bumper", "outstream", "instream"}
# Column headers that only appear in video reports
_VIDEO_COLS = {"start views", "complete views", "video completion rate (vcr)", "vcr"}

def _detect_ad_type_from_buf(buf_bytes: bytes) -> str:
    """
    Detect Video vs Banner by reading column headers from the Excel bytes.
    Video files contain columns like 'Start views', 'VCR', 'Complete Views'.
    Falls back to 'Banner' if columns can't be read.
    """
    try:
        import io as _io
        import openpyxl as _xl
        wb = _xl.load_workbook(_io.BytesIO(buf_bytes), read_only=True, data_only=True)
        ws = wb.active
        # Read first row (headers)
        first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        headers = {str(c).strip().lower() for c in first_row if c is not None}
        wb.close()
        if headers & _VIDEO_COLS:
            return "Video"
    except Exception:
        pass
    return "Banner"

def _detect_ad_type(name: str) -> str:
    """Name-based fallback detection."""
    lower = name.lower()
    for kw in _VIDEO_KW:
        if kw in lower:
            return "Video"
    return "Banner"

def _safe_filename(name: str) -> str:
    """Strip characters that are invalid in filenames."""
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip() or "Sheet"


@router.post("/process")
async def final_report_process(file: UploadFile = File(...)):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in {"xlsx", "xls"}:
        raise HTTPException(status_code=400, detail="Only .xlsx and .xls files accepted.")

    raw = await file.read()
    try:
        blocks = split_excel_to_files(raw, file.filename or "upload.xlsx")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("split_excel_to_files failed")
        raise HTTPException(status_code=500, detail=f"Processing error: {e}")

    stem = (file.filename or "output").rsplit(".", 1)[0]
    results = []

    for block in blocks:
        sheet_name = block["sheet_name"]
        safe_name  = _safe_filename(sheet_name)
        out_name   = f"{stem}_{safe_name}.xlsx"
        out_path   = os.path.join(_FINAL_DIR, out_name)

        # Save to disk
        buf_bytes = block["buf"].getvalue()
        try:
            with open(out_path, "wb") as f_out:
                f_out.write(buf_bytes)
        except Exception as e:
            logger.warning("Could not save final report file %s: %s", out_name, e)

        # Detect ad type:
        # 1. Try full untruncated raw name (B1 for box-type, Line Item value for LI-type)
        raw_name = block.get("raw_name", sheet_name)
        ad_type  = _detect_ad_type(raw_name)
        # 2. If name has no video keywords, fall back to column-header scan
        if ad_type == "Banner":
            ad_type = _detect_ad_type_from_buf(buf_bytes)

        results.append({
            "name":     sheet_name,
            "filename": out_name,
            "ad_type":  ad_type,
        })

    return results


@router.get("/languages")
def get_languages():
    """Return distinct sheet names from app_url_reference (ordered alphabetically)."""
    try:
        conn = _get_ctr_conn()
        cur  = conn.cursor()
        cur.execute("""
            SELECT DISTINCT sheet_name
            FROM   app_url_reference
            ORDER  BY sheet_name
        """)
        names = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return {"languages": names}
    except Exception as e:
        logger.exception("get_languages failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cities")
def get_cities():
    """Return distinct sheet names from city_reference (ordered by total impressions desc)."""
    try:
        conn = _get_ctr_conn()
        cur  = conn.cursor()
        cur.execute("""
            SELECT   sheet_name
            FROM     city_reference
            GROUP BY sheet_name
            ORDER BY SUM(COALESCE(potential_impressions, 0)) DESC NULLS LAST
        """)
        names = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return {"cities": names}
    except Exception as e:
        logger.exception("get_cities failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate")
async def generate_final_report(
    filename:  str  = Form(...),        # split file already on disk in final_report_outputs/
    languages: str  = Form(""),         # comma-separated language sheet names
    cities:    str  = Form(""),         # comma-separated city sheet names
    app_urls:  str  = Form(""),         # newline-separated URLs from textarea
    mode:      str  = Form("video"),
    file2:     UploadFile = File(None), # optional: second file with Creative column
):
    """
    Generate the 10-sheet campaign report Excel from a previously split file.
    Returns the Excel file as a download.
    """
    safe_name = os.path.basename(filename)
    src_path  = os.path.join(_FINAL_DIR, safe_name)
    if not os.path.isfile(src_path):
        raise HTTPException(status_code=404, detail=f"Split file not found: {safe_name}")

    lang_list = [s.strip() for s in languages.split(",") if s.strip()]
    city_list = [s.strip() for s in cities.split(",")    if s.strip()]

    try:
        with open(src_path, "rb") as f:
            file_bytes = f.read()

        creative_bytes = None
        if file2 and file2.filename:
            creative_bytes = await file2.read()

        report_bytes = generate_report(
            campaign_file_bytes  = file_bytes,
            campaign_filename    = safe_name,
            language_sheet_names = lang_list,
            city_sheet_names     = city_list,
            user_urls_text       = app_urls,
            mode                 = mode,
            creative_file_bytes  = creative_bytes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("generate_report failed")
        raise HTTPException(status_code=500, detail=f"Report generation error: {e}")

    stem        = safe_name.rsplit(".", 1)[0]
    report_name = f"report_{stem}.xlsx"
    campaign_name = stem  # use stem as display name (strip "report_" prefix if present)

    # Auto-save to DB
    try:
        _save_report_to_db(campaign_name, report_name, report_bytes)
    except Exception as e:
        logger.warning("Could not save report to DB: %s", e)

    return Response(
        content     = report_bytes,
        media_type  = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers     = {"Content-Disposition": f'attachment; filename="{report_name}"'},
    )


@router.get("/reports")
def list_saved_reports():
    """Return list of all saved reports from DB (without file_data)."""
    try:
        conn = _get_ctr_conn()
        cur  = conn.cursor()
        cur.execute("""
            SELECT id, campaign_name, report_filename,
                   generated_at,
                   octet_length(file_data) AS file_size
            FROM   final_report_store
            ORDER  BY generated_at DESC
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()
        return [
            {
                "id":            r[0],
                "campaign_name": r[1],
                "filename":      r[2],
                "generated_at":  r[3].isoformat() if r[3] else None,
                "file_size":     r[4],
            }
            for r in rows
        ]
    except Exception as e:
        logger.exception("list_saved_reports failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/{report_id}/download")
def download_saved_report(report_id: int):
    """Stream a saved report from DB by its ID."""
    try:
        conn = _get_ctr_conn()
        cur  = conn.cursor()
        cur.execute(
            "SELECT report_filename, file_data FROM final_report_store WHERE id = %s",
            (report_id,),
        )
        row = cur.fetchone()
        cur.close(); conn.close()
    except Exception as e:
        logger.exception("download_saved_report failed")
        raise HTTPException(status_code=500, detail=str(e))

    if not row:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")

    fname, fdata = row
    return Response(
        content    = bytes(fdata),
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers    = {"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.delete("/reports/{report_id}")
def delete_saved_report(report_id: int):
    """Delete a saved report from DB."""
    try:
        conn = _get_ctr_conn()
        cur  = conn.cursor()
        cur.execute("DELETE FROM final_report_store WHERE id = %s RETURNING id", (report_id,))
        deleted = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        logger.exception("delete_saved_report failed")
        raise HTTPException(status_code=500, detail=str(e))

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    return {"deleted": report_id}


@router.get("/download")
def download_final_report_file(file: str):
    safe_name = os.path.basename(file)   # strip any path traversal
    filepath  = os.path.join(_FINAL_DIR, safe_name)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail=f"File not found: {safe_name}")
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )
