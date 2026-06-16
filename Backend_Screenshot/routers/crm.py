"""
CRM Excel Processor router — connected to ctr_db.

POST /crm/process
  Accepts: multipart/form-data
    file     — .xlsx / .xls / .csv upload
    rules    — JSON array of extra campaign rule objects (from frontend form)
    settings — JSON object with global CTR/VCR/Viewability overrides

Pipeline:
  1. Load campaign_rules + global_settings from ctr_db
  2. Merge with any extra rules sent from the frontend form
  3. Load yesterday_memory from ctr_db
  4. Read Excel/CSV → list of row dicts
  5. Call process_rows()
  6. Save today_snapshot → ctr_db.yesterday_memory
  7. Log to ctr_db.processed_files
  8. Return processed .xlsx
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import zipfile
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from database.crm_db import get_crm_db
from models.crm import CampaignRule as CampaignRuleModel
from models.crm import GlobalSetting, ProcessedFile
from schemas.crm import CampaignRule, GlobalSettings
from services.crm_excel_writer import build_excel
from services.crm_memory import load_yesterday_memory, save_today_snapshot
from services.crm_processor import process_rows

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm", tags=["crm"])

# Directory where processed Excel files are persisted for re-download
_PROCESSED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "processed_outputs",
)
os.makedirs(_PROCESSED_DIR, exist_ok=True)


# ── GET /crm/rules ───────────────────────────────────────────────────────────
@router.get("/rules")
def get_campaign_rules(db: Session = Depends(get_crm_db)):
    """Return all campaign_rules rows from ctr_db."""
    try:
        rows = db.query(CampaignRuleModel).order_by(CampaignRuleModel.id).all()
        return [
            {
                "id":               r.id,
                "line_item_id":     r.line_item_id,
                "campaign_name":    r.campaign_name,
                "min_ctr":          r.min_ctr,
                "max_ctr":          r.max_ctr,
                "min_vcr":          r.min_vcr,
                "max_vcr":          r.max_vcr,
                "min_viewability":  r.min_viewability,
                "max_viewability":  r.max_viewability,
                "enabled":          r.enabled,
            }
            for r in rows
        ]
    except Exception as e:
        logger.exception("Could not load campaign_rules")
        raise HTTPException(status_code=500, detail=str(e))


# ── POST /crm/rules ───────────────────────────────────────────────────────────
@router.post("/rules", status_code=201)
def create_campaign_rule(rule: CampaignRule, db: Session = Depends(get_crm_db)):
    """Insert a new row into ctr_db.campaign_rules."""
    try:
        row = CampaignRuleModel(
            line_item_id    = rule.line_id or "",
            campaign_name   = rule.campaign,
            min_ctr         = rule.ctr_min,
            max_ctr         = rule.ctr_max,
            min_vcr         = rule.vcr_min,
            max_vcr         = rule.vcr_max,
            min_viewability = rule.view_min,
            max_viewability = rule.view_max,
            enabled         = True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"id": row.id, "status": "created"}
    except Exception as e:
        db.rollback()
        logger.exception("Could not create campaign_rule")
        raise HTTPException(status_code=500, detail=str(e))


# ── PUT /crm/rules/{rule_id} ─────────────────────────────────────────────────
@router.put("/rules/{rule_id}", status_code=200)
def update_campaign_rule(rule_id: int, rule: CampaignRule, db: Session = Depends(get_crm_db)):
    """Update an existing campaign_rules row by id."""
    try:
        row = db.query(CampaignRuleModel).filter(CampaignRuleModel.id == rule_id).first()
        if not row:
            raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
        row.line_item_id    = rule.line_id or ""
        row.campaign_name   = rule.campaign
        row.min_ctr         = rule.ctr_min
        row.max_ctr         = rule.ctr_max
        row.min_vcr         = rule.vcr_min
        row.max_vcr         = rule.vcr_max
        row.min_viewability = rule.view_min
        row.max_viewability = rule.view_max
        db.commit()
        return {"id": rule_id, "status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Could not update campaign_rule %s", rule_id)
        raise HTTPException(status_code=500, detail=str(e))


# ── DELETE /crm/rules/{rule_id} ───────────────────────────────────────────────
@router.delete("/rules/{rule_id}", status_code=200)
def delete_campaign_rule(rule_id: int, db: Session = Depends(get_crm_db)):
    """Delete a campaign_rules row by id."""
    try:
        row = db.query(CampaignRuleModel).filter(CampaignRuleModel.id == rule_id).first()
        if not row:
            raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
        db.delete(row)
        db.commit()
        return {"id": rule_id, "status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Could not delete campaign_rule %s", rule_id)
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /crm/processed-files ──────────────────────────────────────────────────
@router.get("/processed-files")
def get_processed_files(db: Session = Depends(get_crm_db)):
    """Return all processed file records from ctr_db, newest first."""
    try:
        rows = (
            db.query(ProcessedFile)
            .order_by(ProcessedFile.processed_at.desc())
            .all()
        )
        return [
            {
                "id":                r.id,
                "original_filename": r.original_filename,
                "saved_filename":    r.saved_filename,
                "processed_at":      r.processed_at.isoformat() if r.processed_at else None,
                "ad_type":           r.ad_type or "Banner",
                "downloadable":      bool(
                    r.saved_filename and
                    os.path.isfile(os.path.join(_PROCESSED_DIR, os.path.basename(r.saved_filename)))
                ),
            }
            for r in rows
        ]
    except Exception as e:
        logger.exception("Could not load processed_files")
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /crm/download/{filename} ─────────────────────────────────────────────
@router.get("/download/{filename}")
def download_processed_file(filename: str):
    """Serve a previously processed Excel file for re-download."""
    # Sanitise — no path traversal
    safe_name = os.path.basename(filename)
    filepath = os.path.join(_PROCESSED_DIR, safe_name)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File not found — it may have been cleared.")
    media = "text/csv; charset=utf-8" if safe_name.endswith(".csv") else \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(
        filepath,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


# ── Load rules from ctr_db ────────────────────────────────────────────────────
def _load_db_rules(db: Session) -> dict:
    """
    Read enabled campaign_rules rows from ctr_db and convert to the
    lookup dict process_rows() expects.

    Keyed by (lower-cased):
      • line_item_id
      • campaign_name  (if set)
    """
    rules_dict: dict = {}
    try:
        rows = (
            db.query(CampaignRuleModel)
            .filter(CampaignRuleModel.enabled.is_(True))
            .all()
        )
        for r in rows:
            entry: dict = {}
            if r.min_ctr         is not None: entry["min_ctr"]         = r.min_ctr
            if r.max_ctr         is not None: entry["max_ctr"]         = r.max_ctr
            if r.min_vcr         is not None: entry["min_vcr"]         = r.min_vcr
            if r.max_vcr         is not None: entry["max_vcr"]         = r.max_vcr
            if r.min_viewability is not None: entry["min_viewability"]  = r.min_viewability
            if r.max_viewability is not None: entry["max_viewability"]  = r.max_viewability

            if r.line_item_id:
                rules_dict[r.line_item_id.strip().lower()] = entry
            if r.campaign_name:
                rules_dict[r.campaign_name.strip().lower()] = entry
    except Exception as e:
        logger.warning("Could not load campaign_rules from DB: %s", e)
    return rules_dict


def _load_global_settings(db: Session, fallback: GlobalSettings) -> GlobalSettings:
    """
    Read global_settings row (id=1) from ctr_db.
    Only CTR min/max are stored there; VCR and Viewability come from the request fallback.
    """
    try:
        row = db.query(GlobalSetting).first()
        if row:
            return GlobalSettings(
                ctr_min=row.min_ctr if row.min_ctr is not None else fallback.ctr_min,
                ctr_max=row.max_ctr if row.max_ctr is not None else fallback.ctr_max,
                vcr_min=fallback.vcr_min,
                vcr_max=fallback.vcr_max,
                view_min=fallback.view_min,
                view_max=fallback.view_max,
            )
    except Exception as e:
        logger.warning("Could not load global_settings from DB: %s", e)
    return fallback


# ── Merge form rules into rules dict ─────────────────────────────────────────
def _merge_form_rules(base: dict, form_rules: list[CampaignRule]) -> dict:
    """
    Form-submitted rules OVERRIDE DB rules for the same key.
    This lets the frontend UI make one-off adjustments without editing the DB.
    """
    merged = dict(base)
    for rule in form_rules:
        entry: dict = {}
        if rule.ctr_min  is not None: entry["min_ctr"]         = rule.ctr_min
        if rule.ctr_max  is not None: entry["max_ctr"]         = rule.ctr_max
        if rule.vcr_min  is not None: entry["min_vcr"]         = rule.vcr_min
        if rule.vcr_max  is not None: entry["max_vcr"]         = rule.vcr_max
        if rule.view_min is not None: entry["min_viewability"]  = rule.view_min
        if rule.view_max is not None: entry["max_viewability"]  = rule.view_max

        for name in rule.campaign.split(","):
            key = name.strip().lower()
            if key:
                merged[key] = {**merged.get(key, {}), **entry}
        if rule.line_id:
            k = rule.line_id.strip().lower()
            merged[k] = {**merged.get(k, {}), **entry}

    return merged


# ── Ad type detection ─────────────────────────────────────────────────────────
_VIDEO_KEYWORDS = {"video", "vid", "15s", "30s", "6s", "bumper", "outstream", "instream"}

def _detect_ad_type(sheet_name: str) -> str:
    """Return 'Video' if the sheet name contains a video keyword, else 'Banner'."""
    lower = sheet_name.lower()
    for kw in _VIDEO_KEYWORDS:
        if kw in lower:
            return "Video"
    return "Banner"


# ── File reader ───────────────────────────────────────────────────────────────
def _read_file(data: bytes, filename: str) -> dict[str, list[dict]]:
    """
    Read all sheets from an Excel file (or the single CSV).
    Returns {sheet_name: [row_dicts]} — empty sheets are skipped.
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    buf = io.BytesIO(data)
    if ext == "csv":
        df = pd.read_csv(buf, dtype=str, keep_default_na=False, na_values=[""])
        df = df.where(pd.notnull(df), None)
        sheet_stem = filename.rsplit(".", 1)[0]
        rows = df.to_dict(orient="records")
        return {sheet_stem: rows} if rows else {}
    else:
        all_sheets = pd.read_excel(
            buf, sheet_name=None, dtype=object,
            keep_default_na=False, na_values=[""],
        )
        result = {}
        for sheet_name, df in all_sheets.items():
            df = df.where(pd.notnull(df), None)
            rows = df.to_dict(orient="records")
            if rows:
                result[sheet_name] = rows
        return result


# ── Endpoint ──────────────────────────────────────────────────────────────────
@router.post("/process")
async def crm_process(
    file: UploadFile = File(...),
    rules: str = Form(default="[]"),
    settings: str = Form(default="{}"),
    db: Session = Depends(get_crm_db),
):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in {"xlsx", "xls", "csv"}:
        raise HTTPException(status_code=400, detail="Only .xlsx, .xls, .csv files accepted.")

    # Parse form data
    try:
        form_rules = [CampaignRule(**r) for r in json.loads(rules)]
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid rules JSON: {e}")

    try:
        form_settings = (
            GlobalSettings(**json.loads(settings))
            if settings.strip() not in ("{}", "")
            else GlobalSettings()
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid settings JSON: {e}")

    # Load from ctr_db
    db_rules        = _load_db_rules(db)
    global_settings = _load_global_settings(db, form_settings)
    campaign_rules  = _merge_form_rules(db_rules, form_rules)
    yesterday_mem   = load_yesterday_memory(db)

    logger.info(
        "CRM process: file=%s db_rules=%d form_rules=%d yesterday_lines=%d",
        file.filename, len(db_rules), len(form_rules), len(yesterday_mem),
    )

    # Read file — returns {sheet_name: [rows]} for all sheets
    raw = await file.read()
    try:
        sheets = _read_file(raw, file.filename or "upload.xlsx")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read file: {e}")

    if not sheets:
        raise HTTPException(status_code=400, detail="File is empty or has no data rows.")

    stem = re.sub(r"\.[^.]+$", "", file.filename or "output")
    merged_snapshot: dict = {}

    # Process each sheet independently, collect (name, csv_bytes) pairs
    processed_csvs: list[tuple[str, bytes]] = []

    for sheet_name, rows in sheets.items():
        if not rows:
            continue
        try:
            output_rows, today_snapshot = process_rows(
                rows=rows,
                yesterday_memory=yesterday_mem,
                global_min_ctr=global_settings.ctr_min,
                global_max_ctr=global_settings.ctr_max,
                campaign_ctr_rules=campaign_rules,
            )
        except Exception as e:
            logger.exception("process_rows failed for sheet %s", sheet_name)
            raise HTTPException(status_code=500, detail=f"Processing error on sheet '{sheet_name}': {e}")

        # Merge snapshots across sheets
        for lid, entries in today_snapshot.items():
            merged_snapshot.setdefault(lid, []).extend(entries)

        # Build CSV bytes for this sheet
        try:
            df  = pd.DataFrame(output_rows)
            buf = io.BytesIO()
            df.to_csv(buf, index=False, encoding="utf-8-sig")
            csv_bytes = buf.getvalue()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"CSV build error on sheet '{sheet_name}': {e}")

        # Safe sheet name for filename (strip invalid chars)
        safe_sheet = re.sub(r'[\\/*?:"<>|]', "_", sheet_name).strip() or "Sheet"
        # Single sheet from CSV: don't add sheet suffix (keep old naming)
        if len(sheets) == 1:
            out_name = f"processed_{stem}.csv"
        else:
            out_name = f"processed_{stem}_{safe_sheet}.csv"

        # Save to disk
        try:
            out_path = os.path.join(_PROCESSED_DIR, out_name)
            with open(out_path, "wb") as f_out:
                f_out.write(csv_bytes)
        except Exception as e:
            logger.warning("Could not save processed file to disk: %s", e)

        # Log to processed_files table
        ad_type = _detect_ad_type(sheet_name)
        try:
            db.add(ProcessedFile(
                original_filename=file.filename,
                saved_filename=out_name,
                processed_at=datetime.now(timezone.utc),
                ad_type=ad_type,
            ))
            db.commit()
        except Exception as e:
            logger.warning("Could not log to processed_files: %s", e)

        processed_csvs.append((out_name, csv_bytes, ad_type))

    # Persist merged yesterday_memory snapshot
    try:
        save_today_snapshot(db, merged_snapshot)
    except Exception as e:
        logger.warning("Could not save today snapshot: %s", e)

    # ── Return ────────────────────────────────────────────────────────────────
    if len(processed_csvs) == 1:
        # Single sheet → stream CSV directly (same as before)
        out_name, csv_bytes, _ = processed_csvs[0]
        return StreamingResponse(
            io.BytesIO(csv_bytes),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
        )
    else:
        # Multiple sheets → ZIP all CSVs
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data, _ in processed_csvs:
                zf.writestr(name, data)
        zip_buf.seek(0)
        zip_name = f"processed_{stem}.zip"
        return StreamingResponse(
            zip_buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
        )
