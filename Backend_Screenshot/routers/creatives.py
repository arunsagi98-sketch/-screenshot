"""
Creatives router — upload, list, delete creative images.
"""
import logging
import os

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from core.auth import require_api_key
from core.paths import get_paths

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Creatives"])


@router.post("/upload-creatives")
async def upload_creatives(request: Request, _: None = Depends(require_api_key)):
    """Accept one or more creative images via multipart form upload."""
    input_dir = get_paths()["input_images"]
    os.makedirs(input_dir, exist_ok=True)

    try:
        form = await request.form()
    except Exception:
        logger.exception("Failed to parse multipart form")
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Invalid multipart form data."},
        )

    # Accept files under any common field name
    upload_files = []
    for key in ("files", "files[]", "images", "image", "creatives"):
        candidates = [v for v in form.getlist(key) if hasattr(v, "filename") and v.filename]
        if candidates:
            upload_files = candidates
            break
    if not upload_files:
        for _key, value in form.multi_items():
            if hasattr(value, "filename") and value.filename:
                upload_files.append(value)

    logger.info("Upload request: %d file(s) found in form", len(upload_files))
    if not upload_files:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "No image files received."},
        )

    saved = []
    for file in upload_files:
        try:
            content = await file.read()
            dest = os.path.join(input_dir, os.path.basename(file.filename))
            with open(dest, "wb") as out:
                out.write(content)
            saved.append(os.path.basename(file.filename))
        except Exception:
            logger.exception("Failed to save creative: %s", file.filename)
        finally:
            await file.close()

    if not saved:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "All files failed to save."},
        )
    logger.info("Upload complete: %s", saved)
    return {"status": "success", "uploaded": saved, "count": len(saved)}


@router.delete("/delete-creative")
async def delete_creative(filename: str = Query(...), _: None = Depends(require_api_key)):
    """Delete a single uploaded creative by filename."""
    input_dir = get_paths()["input_images"]
    safe   = os.path.basename(filename)
    target = os.path.abspath(os.path.join(input_dir, safe))
    if not target.startswith(input_dir + os.sep):
        return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid filename"})
    if not os.path.isfile(target):
        return JSONResponse(status_code=404, content={"status": "error", "message": "Creative not found"})
    try:
        os.unlink(target)
    except OSError as exc:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})
    logger.info("Deleted creative: %s", safe)
    return {"status": "success", "deleted": safe}


@router.get("/creatives")
def list_creatives(_: None = Depends(require_api_key)):
    """List all uploaded creatives with name, file size, and image dimensions."""
    from PIL import Image as PILImage

    input_dir = get_paths()["input_images"]
    supported = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    files = []
    if os.path.isdir(input_dir):
        for name in sorted(os.listdir(input_dir)):
            fp = os.path.join(input_dir, name)
            if not os.path.isfile(fp):
                continue
            if os.path.splitext(name)[1].lower() not in supported:
                continue
            entry = {"name": name, "size": os.path.getsize(fp), "width": None, "height": None}
            try:
                with PILImage.open(fp) as img:
                    entry["width"], entry["height"] = img.size
            except Exception:
                pass
            files.append(entry)
    return {"count": len(files), "files": files}


@router.get("/creatives/debug")
def creatives_debug(_: None = Depends(require_api_key)):
    """Debug endpoint — list raw files in the input_images directory."""
    input_dir = get_paths()["input_images"]
    files = []
    if os.path.isdir(input_dir):
        for name in sorted(os.listdir(input_dir)):
            fp = os.path.join(input_dir, name)
            if os.path.isfile(fp):
                files.append({"name": name, "size": os.path.getsize(fp)})
    return {"input_dir": input_dir, "count": len(files), "files": files}
