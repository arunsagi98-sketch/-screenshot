# Creative Scanner Pro — Architecture

## What the project does

An **ad verification platform**. Give it a list of URLs and your creative images.
It launches a headless Chromium browser, detects ad slots on each page, overlays your
creatives, takes a full-page screenshot, and stores the result in PostgreSQL.
A dashboard lets you manage runs, view screenshots, and export PPT reports.

---

## Directory Structure

```
$Screenshot/                             ← project root
│
├── ARCHITECTURE.md                      ← this file
├── .env                                 ← secrets (never commit)
├── .gitignore
│
├── Backend_Screenshot/                  ← Python FastAPI backend
│   ├── main.py                          ← app factory: middleware, routers, static mounts
│   ├── run.py                           ← uvicorn launcher (dev + Render)
│   ├── alembic.ini                      ← Alembic configuration
│   ├── requirements.txt
│   │
│   ├── core/                            ← cross-cutting infrastructure
│   │   ├── config.py                    ← all settings from env vars (Pydantic Settings)
│   │   ├── logging.py                   ← structured logging setup
│   │   ├── auth.py                      ← API key dependency (Depends(require_api_key))
│   │   └── paths.py                     ← computed filesystem paths (single source of truth)
│   │
│   ├── routers/                         ← one file per feature domain
│   │   ├── scan.py                      ← POST /process  (streams NDJSON)
│   │   ├── results.py                   ← GET/DELETE /results, POST /results/export-ppt
│   │   ├── creatives.py                 ← /upload-creatives, /delete-creative, /creatives
│   │   ├── ppt_store.py                 ← /ppt-store/* (templates + saved reports)
│   │   └── utilities.py                 ← /health, /get-image-base64, /ppt-export-assets, /api/vpn/*
│   │
│   ├── schemas/                         ← Pydantic request/response models
│   │   ├── scan.py                      ← ScanRequest
│   │   ├── results.py                   ← ExportPPTRequest, ResultItem
│   │   └── creatives.py                 ← CreativeFile, CreativesListResponse
│   │
│   ├── database/
│   │   └── db.py                        ← engine, SessionLocal, get_db() dependency
│   │
│   ├── models/
│   │   └── screenshot.py                ← ScreenshotResult SQLAlchemy ORM model
│   │
│   ├── services/                        ← business logic (no HTTP concerns)
│   │   ├── browser.py                   ← Playwright orchestrator
│   │   ├── ad_detector.py               ← DOM/CSS ad slot detection + confidence scoring
│   │   ├── image_utils.py               ← creative matching (aspect/size/IAB scoring)
│   │   ├── db_service.py                ← CRUD helpers
│   │   ├── ppt_exporter.py              ← PPTX report generation
│   │   ├── ppt_style_extractor.py       ← extract theme colours from a PPTX template
│   │   ├── smart_placement.py           ← 3-level fallback ad placement
│   │   └── vision_detector.py           ← Claude Vision AI ad detection
│   │
│   ├── migrations/                      ← Alembic DB migrations
│   │   ├── env.py                       ← Alembic runtime config
│   │   ├── script.py.mako               ← migration file template
│   │   └── versions/
│   │       └── 0001_initial_schema.py   ← initial table creation
│   │
│   └── tests/
│       ├── test_api.py
│       └── test_image_utils.py
│
├── Frontend_Screenshot/                 ← Vanilla JS dashboard (no bundler)
│   ├── index.html                       ← main page
│   ├── ppt-store.html                   ← PPT store page
│   ├── style.css                        ← global styles
│   ├── package.json                     ← dev scripts (lint, format, local serve)
│   │
│   └── src/                             ← ES modules (active implementation)
│       ├── main.js                      ← entry point (loaded by index.html)
│       ├── config/apiConfig.js          ← API base URL
│       ├── constants/                   ← shared enums + config
│       ├── core/                        ← DOM helpers, EventEmitter, HTTPClient, Logger
│       ├── modules/
│       │   ├── Application.js           ← top-level app orchestrator
│       │   ├── ResultsRenderer.js       ← renders scan result cards
│       │   ├── StateManager.js          ← centralised UI state
│       │   ├── ToastComponent.js        ← toast notifications
│       │   └── apiServices.js           ← all fetch() calls (active)
│       ├── services/apiService.js       ← legacy service layer (used by index.js only)
│       ├── state/appState.js            ← reactive application state
│       ├── styles/variables.css         ← CSS custom properties
│       ├── ui/                          ← low-level UI helpers
│       └── utils/helpers.js             ← pure utility functions
│
├── input_images/                        ← upload your creative PNGs/JPGs here
└── screenshots/                         ← generated screenshots (gitignored)
```

---

## Key Design Decisions

### Backend

**Routers** (`routers/`) — each file owns one feature domain. `main.py` only wires them together; it contains no route logic.

**Schemas** (`schemas/`) — Pydantic models for all request/response bodies. Routes accept typed schemas, not raw `dict`.

**Paths** (`core/paths.py`) — all filesystem paths are computed once from `get_settings()` and cached. No more scattered `os.path.join(_BACKEND_ROOT, ...)` strings in route handlers.

**Alembic** (`migrations/`) — proper schema versioning. Run `alembic upgrade head` instead of the `ALTER TABLE` guard in `startup_event`. The guard is still present as a fallback for existing deployments.

### Frontend

The active implementation is `src/main.js` → `src/modules/Application.js`. The `src/index.js` is a legacy monolithic file that is no longer loaded; it can be deleted once the module system is verified complete.

---

## How to Run

```bash
# 1. Copy and fill in environment variables
cp Backend_Screenshot/.env.example Backend_Screenshot/.env

# 2. Install Python dependencies
cd Backend_Screenshot
pip install -r requirements.txt
playwright install chromium

# 3. Apply DB migrations
alembic upgrade head

# 4. Start the server
python run.py
# API:   http://127.0.0.1:8001
# UI:    http://127.0.0.1:8001/ui/
# Docs:  http://127.0.0.1:8001/docs
```

---

## API Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET  | `/health`                      | —  | Liveness probe |
| GET  | `/results`                     | ✓  | All scan results |
| DELETE | `/results/{id}`              | ✓  | Delete a result |
| POST | `/results/export-ppt`          | ✓  | Export results as PPTX |
| POST | `/upload-creatives`            | ✓  | Upload creative images |
| DELETE | `/delete-creative`           | ✓  | Delete a creative |
| GET  | `/creatives`                   | ✓  | List uploaded creatives |
| POST | `/process`                     | ✓  | Run a scan (streams NDJSON) |
| GET  | `/get-image-base64`            | ✓  | Fetch image as base64 |
| GET  | `/ppt-export-assets`           | ✓  | PPT theme + asset data |
| GET  | `/ppt-store/templates`         | ✓  | List PPTX templates |
| POST | `/ppt-store/templates/upload`  | ✓  | Upload a template |
| DELETE | `/ppt-store/templates/{name}` | ✓ | Delete a template |
| POST | `/ppt-store/export`            | ✓  | Generate + save a report |
| GET  | `/ppt-store/reports`           | ✓  | List saved reports |
| DELETE | `/ppt-store/reports/{name}`  | ✓  | Delete a saved report |

Full interactive docs: `http://127.0.0.1:8001/docs`
