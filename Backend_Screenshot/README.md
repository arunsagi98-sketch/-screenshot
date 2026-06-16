# Backend Screenshot

FastAPI backend for generating browser screenshots, detecting ad slots, placing local creatives, storing results, and exporting reports.

## Run Locally

Run all commands from the project root:

```powershell
cd "c:\Users\HP\Desktop\$Screenshot\Backend_Screenshot"
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
python run.py
```

The API starts at:

```text
http://127.0.0.1:8000
```

Useful endpoints:

```text
GET  /health
GET  /results
POST /process
POST /upload-creatives
POST /results/export-pdf
```

## Checks

```powershell
python verify_system.py
python test_api.py
python test_pass2.py
```

## Current Code Ownership

Keep future corrections focused in the right file:

```text
main.py                         FastAPI app, routes, request/response flow
run.py                          Local uvicorn launcher
services/browser.py             Playwright browsing, scrolling, placement, screenshots
services/ad_detector.py         DOM/network ad slot detection
services/image_utils.py         Creative loading and matching
services/db_service.py          Screenshot result persistence
services/pdf_exporter.py        PDF report generation
services/ppt_style_extractor.py PPT theme/style extraction
database/db.py                  Database connection/session setup
models/screenshot.py            Database model
screenshots/                    Generated screenshots
ppt_assets/                     Extracted/exported PPT assets
```

## Target Industry-Level Structure

For future refactors, move toward this layout gradually. Do not do this in one large risky change unless tests are green.

```text
Backend_Screenshot/
  app/
    main.py
    api/
      routes/
        screenshots.py
        creatives.py
        vpn.py
        export.py
    core/
      config.py
      logging.py
    services/
      browser.py
      ad_detector.py
      image_utils.py
      db_service.py
      pdf_exporter.py
      ppt_style_extractor.py
    models/
      screenshot.py
    database/
      db.py
  tests/
    test_api.py
    test_browser.py
    test_ad_detector.py
  scripts/
    create_tables.py
    reset_db.py
    check_images.py
  storage/
    screenshots/
    ppt_assets/
    extracted_ppt_media/
  requirements.txt
  README.md
  run.py
```

## Correction Rules

- Keep API route changes separate from browser automation changes.
- Keep database writes inside database/service modules, not route handlers.
- Add small tests for each bug fix when possible.
- Avoid broad refactors while fixing production bugs.
- Keep generated files, logs, screenshots, and local virtual environments out of git.
