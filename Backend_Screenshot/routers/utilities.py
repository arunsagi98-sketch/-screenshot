"""
Utilities router — health check, image base64, PPT assets, VPN stub, Excel→CSV converter.
"""
import io
import logging
import os
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from core.auth import require_api_key
from core.config import get_settings
from core.paths import get_paths

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Utilities"])


# ── Colour helpers (used by /ppt-export-assets) ───────────────────────────────

def _hex_clean(h: str, default: str) -> str:
    v = (h or "").strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return v.upper() if len(v) == 6 and all(c in "0123456789ABCDEFabcdef" for c in v) else default


def _blend(a: str, b: str, ratio: float) -> str:
    """Linear-blend two hex colours by ratio (0 = full a, 1 = full b)."""
    a, b = _hex_clean(a, "FFFFFF"), _hex_clean(b, "000000")
    return "".join(
        f"{int(round(int(a[i:i+2], 16) + (int(b[i:i+2], 16) - int(a[i:i+2], 16)) * ratio)):02X}"
        for i in (0, 2, 4)
    )


# ── Routes ────────────────────────────────────────────────────────────────────

# ── Excel → CSV Converter ─────────────────────────────────────────────────────
_ENGINE_MAP = {
    "xlsx": "openpyxl",
    "xls":  "xlrd",
    "xlsm": "openpyxl",
    "ods":  "odf",
}

@router.post("/convert/excel-to-csv", tags=["Utilities"])
async def excel_to_csv(
    file: UploadFile = File(...),
    _: None = Depends(require_api_key),
):
    """
    Convert any Excel file (.xlsx, .xls, .xlsm, .ods) to CSV.
    Reads the first sheet and returns a UTF-8 CSV file for download.
    """
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    engine = _ENGINE_MAP.get(ext)

    if engine is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: .{ext}. Please upload .xlsx, .xls, .xlsm, or .ods",
        )

    raw = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(raw), sheet_name=0, engine=engine)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read Excel file: {e}")

    if df.empty:
        raise HTTPException(status_code=400, detail="Excel file is empty.")

    # Convert to CSV
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    buf.seek(0)

    csv_filename = (file.filename or "output").rsplit(".", 1)[0] + ".csv"
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{csv_filename}"'},
    )


@router.get("/health", tags=["System"])
def health():
    """Liveness probe — returns 200 + current environment name."""
    return {"status": "online", "env": get_settings().app_env}


@router.get("/ping", tags=["System"])
def ping():
    """
    Lightweight keep-alive endpoint — no auth, no DB query.
    Point an external cron (cron-job.org, UptimeRobot, etc.) at this URL
    every 10 minutes to prevent Render from spinning down the service.
    """
    return {"pong": True}


@router.get("/get-image-base64")
async def get_image_base64(path: str, _: None = Depends(require_api_key)):
    """Return a single image as a base64 data-URL. Searched across all image folders."""
    import base64

    paths = get_paths()
    clean = os.path.basename(path)
    search_dirs = (
        paths["screenshots"],
        paths["ppt_assets"],
        os.path.join(paths["screenshots"], "..", "extracted_ppt_media"),
        paths["input_images"],
    )
    for folder in search_dirs:
        candidate = os.path.join(folder, clean)
        if os.path.isfile(candidate):
            ext  = clean.rsplit(".", 1)[-1].lower()
            mime = f"image/{ext}" if ext in ("png", "jpeg", "jpg", "webp") else "image/jpeg"
            with open(candidate, "rb") as f:
                return {"dataUrl": f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"}
    return JSONResponse(status_code=404, content={"error": "Image not found"})


@router.get("/ppt-export-assets")
def ppt_export_assets(_: None = Depends(require_api_key)):
    """Return PPT theme colours + cover/logo/gradient images as base64 data-URLs."""
    import base64
    from services.ppt_style_extractor import extract_ppt_assets, get_ppt_file_path, get_ppt_styles

    paths = get_paths()

    def _data_url(p: str) -> Optional[str]:
        if not p or not os.path.isfile(p):
            return None
        ext  = p.rsplit(".", 1)[-1].lower()
        mime = "image/png" if ext == "png" else "image/jpeg"
        with open(p, "rb") as f:
            return f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"

    accent_d = "6366F1"
    theme = {
        "accent": accent_d, "background": "F8FAFC",
        "title": "1E293B", "text": "334155",
        "gradientTop": "EEF2FF", "gradientBottom": "C7D2FE",
    }

    ppt_path = get_ppt_file_path()
    if ppt_path and (styles := get_ppt_styles()):
        accent = _hex_clean(styles.get("accent_color"), accent_d)
        theme.update({
            "accent": accent,
            "title": _hex_clean(styles.get("title_color"), theme["title"]),
            "text": _hex_clean(styles.get("text_color"), theme["text"]),
            "background": _hex_clean(styles.get("background_color"), theme["background"]),
            "gradientTop": _blend("FFFFFF", accent, 0.12),
            "gradientBottom": _blend(theme["background"], accent, 0.28),
        })

    p = paths["ppt_assets"]
    cover = logo = None
    if ppt_path and (assets := extract_ppt_assets()):
        cover = _data_url(assets.get("background"))
        logo  = _data_url(assets.get("logo"))

    cover     = cover or _data_url(os.path.join(p, "cover_bg.jpg"))
    gradient  = _data_url(os.path.join(p, "gradient_bg.jpg"))
    logo      = logo  or _data_url(os.path.join(p, "billiontags_logo.png"))
    text_fill = _data_url(os.path.join(p, "text_fill.png"))

    return {"theme": theme, "cover": cover, "logo": logo, "gradient": gradient, "textFill": text_fill}


# ── VPN (stub — wire up a real provider here) ─────────────────────────────────

@router.get("/api/vpn/status", tags=["VPN"])
def vpn_status():
    return {"ip": "Local", "city": "Not configured", "country": "VPN", "connected": False}


@router.post("/api/vpn/toggle", tags=["VPN"])
async def vpn_toggle(data: dict):
    return {"success": False, "message": "VPN not configured.", "requested": data}
