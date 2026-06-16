"""
Scan router — POST /process
Streams NDJSON progress events while Playwright visits each URL.
"""
import asyncio
import json
import logging
import re
from typing import List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from core.auth import require_api_key
from services.browser import open_website

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Scan"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_urls(raw) -> List[str]:
    """Accept a list, comma/newline-separated string, or single string."""
    if isinstance(raw, list):
        return [str(u).strip() for u in raw if str(u).strip()]
    if isinstance(raw, str):
        return [u.strip() for u in re.split(r"[,\n\s]+", raw) if u.strip()]
    if raw is None:
        return []
    return [str(raw).strip()] if str(raw).strip() else []


async def _parse_payload(request: Request):
    """Parse request body — supports JSON, multipart form, and query params."""
    ct = (request.headers.get("content-type") or "").lower()
    if "json" in ct or "form" not in ct:
        try:
            return await request.json()
        except Exception:
            pass
    if "form" in ct:
        try:
            return dict(await request.form())
        except Exception:
            pass
    q = request.query_params.get("urls")
    return {"urls": q} if q else None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/process", tags=["Scan"])
async def process_urls(request: Request, _: None = Depends(require_api_key)):
    """
    Launch a headless browser scan for the given URLs.
    Streams back NDJSON events: started → site_* → match_* → finished|error
    """
    payload = await _parse_payload(request)
    raw, device = [], "desktop"
    if isinstance(payload, dict):
        raw    = payload.get("urls", [])
        device = payload.get("device", "desktop")
    elif isinstance(payload, (list, str)):
        raw = payload

    device   = "mobile" if str(device).lower() == "mobile" else "desktop"
    url_list = _normalize_urls(raw)
    logger.info("POST /process — %d URL(s) [device=%s]", len(url_list), device)

    if not url_list:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "No valid URLs found in request"},
        )

    async def event_stream():
        q: asyncio.Queue = asyncio.Queue()

        async def emit(event):
            await q.put(event)

        task = asyncio.create_task(open_website(urls=url_list, emit_cb=emit, device=device))
        while True:
            get_item = asyncio.create_task(q.get())
            done, _ = await asyncio.wait([get_item, task], return_when=asyncio.FIRST_COMPLETED)
            if get_item in done:
                event = get_item.result()
                yield json.dumps(event) + "\n"
                if event.get("type") in ("finished", "error"):
                    break
            else:
                get_item.cancel()
                while not q.empty():
                    yield json.dumps(q.get_nowait()) + "\n"
                if task.exception():
                    yield json.dumps({"type": "error", "payload": {"message": str(task.exception())}}) + "\n"
                break

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
