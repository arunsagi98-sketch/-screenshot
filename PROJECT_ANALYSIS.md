# Creative Scanner Pro — Project Analysis

**Date:** 2026-06-16  
**Codebase:** ~100 files across Backend_Screenshot/ and Frontend_Screenshot/

---

## What the Project Does

**Creative Scanner Pro** (branded "AdVision AI" in the frontend) is an **ad verification and simulation platform**. Given a list of URLs and creative images, it:

1. Opens each URL in a headless Chromium browser (Playwright)
2. Detects ad slots using DOM/CSS heuristics, GPT API signals, and network interception
3. Injects your creative image into the best-matching slot
4. Captures a before/after screenshot
5. Exports branded PowerPoint reports

The platform also bundles a **CRM Excel Processor** (CTR/VCR/Viewability calculations) and a **Final Report generator** (Excel file splitting by language/city), making it a multi-tool ad-ops suite.

---

## Architecture

```
$Screenshot/
├── Backend_Screenshot/   ← FastAPI (Python 3.11+)
│   ├── core/             ← config, auth, security, logging, paths
│   ├── routers/          ← one file per feature domain
│   ├── services/         ← all business logic (no HTTP)
│   ├── models/           ← SQLAlchemy ORM
│   ├── schemas/          ← Pydantic request/response types
│   ├── database/         ← two DB engines (scanner.db + ctr_db)
│   └── migrations/       ← Alembic versioned migrations
└── Frontend_Screenshot/  ← Vanilla JS (ES modules, no bundler)
    └── src/              ← Application.js orchestrator + modules
```

**Two databases:** `scanner.db` (scan results, users) and `ctr_db` (CRM data, screenshots). Both are SQLite locally and swap to PostgreSQL via `DATABASE_URL`/`CRM_DATABASE_URL` env vars.

**Auth:** Dual-mode — JWT Bearer tokens (role-based, preferred) or `X-API-Key` header (legacy). Roles: `super_admin` (full access) and `admin` (page-restricted via JSON column).

---

## Core Engine — How Ad Injection Works

### Two-Pass Strategy

**Pass 1 — In-slot injection:**  
DOM scanner + network interception find real ad slots. A multi-factor scoring algorithm matches the best creative to each slot (0.0–1.0 score). The creative is overlaid on `document.body` as an absolutely-positioned div — placed *outside* any ad-network DOM subtree so GPT refresh cycles can't overwrite it.

**Pass 2 — Natural placement fallback:**  
If no matching slots are found, three sub-strategies are tried in order:
1. Structural DOM (find header bottom or sidebar gap — free and instant)
2. Claude Vision (AI picks the best position from a screenshot — ~$0.001/call)
3. Native article insertion (inserts between paragraphs as a "Sponsored" block)

### Creative Matching Algorithm

| Factor | Weight |
|--------|--------|
| Aspect ratio match | 40% |
| Size proximity | 30% |
| Orientation (H/V) | 20% |
| IAB standard size bonus | 10% |

Minimum score to qualify: 0.40.

### Anti-Bot / Reliability Measures
- `playwright-stealth` + custom `navigator.webdriver` masking init script
- Navigation retry with exponential backoff (3 attempts)
- Early Cloudflare/reCAPTCHA detection — skips blocked pages rather than hanging
- Consent banner automation (OneTrust, Quantcast, Cookiebot, generic CMPs)
- CSP header stripping so injection JS is never blocked

---

## Strengths

**Clean architecture.** Routers contain zero business logic — all of it lives in `services/`. Pydantic schemas type every request/response. `core/paths.py` centralises all filesystem paths. `core/config.py` is a single Pydantic Settings class — no scattered `os.getenv()` calls in most files.

**Good documentation.** README, ARCHITECTURE.md, CORE_ENGINE.md, and per-file docstrings are thorough and accurate.

**Robust scan pipeline.** The two-pass strategy with three-level fallback means nearly every URL produces a result regardless of how the site serves ads. The overlay-on-body approach specifically solves the problem of GPT re-firing and overwriting injected creatives.

**Streaming API.** The `/process` endpoint returns NDJSON — the frontend shows real-time progress per URL without polling.

**Alembic migrations.** Proper version-controlled schema migration exists (3 migration files). A startup guard runs `ALTER TABLE … ADD COLUMN IF NOT EXISTS` as a backward-compat safety net.

**Security basics.** Passwords use bcrypt directly, JWT tokens are HS256, path traversal is blocked on the delete-creative endpoint, and API key auth can be disabled for dev.

---

## Issues and Technical Debt

### High Priority

**1. `browser.py` is 2,350 lines — a monolith.**  
This single file contains: stealth scripts, navigation helpers, popup handlers, security detection, scroll logic, screenshot logic, three injection strategies, two JS blobs (one dead), address bar rendering, and the main orchestrator. It is very difficult to unit-test or maintain. It should be split into at least: `browser_nav.py`, `browser_inject.py`, `browser_screenshot.py`, and `browser_orchestrator.py`.

**2. Hardcoded JWT secret default.**  
`core/security.py` line 14:
```python
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production-supersecret-key")
```
If `JWT_SECRET` is not set, all environments use the same public default. This should raise a `ValueError` in production (`app_env == "production"`) rather than silently accepting the insecure default.

**3. CORS is open.**  
`main.py` has `allow_origins=["*"]` with a comment saying "Lock this to your domain in production." This is never enforced programmatically. Conditional logic based on `settings.app_env` should restrict origins in production.

**4. Dead code: `_PASS1_PLACEMENT_JS_OLD`.**  
Lines ~1236–1441 of `browser.py` are a 205-line JavaScript blob explicitly commented "kept for reference, not used." This should be deleted (it's in git history if needed).

### Medium Priority

**5. `@app.on_event("startup")` is deprecated.**  
FastAPI has deprecated event decorators since v0.93. The startup block should be replaced with an `@asynccontextmanager` lifespan function. The deprecation warning will become an error in a future FastAPI release.

**6. Startup migration guard mixes with Alembic.**  
The raw `ALTER TABLE` guard in `startup_event` duplicates what Alembic migration `0001` already does. The comment says "Replace this with Alembic once you adopt proper migrations" — but Alembic is already adopted. The guard should be removed and `alembic upgrade head` should be the sole migration mechanism.

**7. Scattered standalone test files.**  
`test_api.py`, `test_scan.py`, `test_db.py`, `test_comprehensive.py` sit in `Backend_Screenshot/` root outside the `tests/` folder and aren't collected by pytest by default. The formal test suite in `tests/` has only 5 test cases — very low coverage for the core scan/injection logic.

**8. `browser.py` bypasses `core/paths.py` for the screenshots directory.**  
Line 1571: `os.makedirs("screenshots", exist_ok=True)` and `f"screenshots/{domain}.png"` hardcode a relative path. All other path construction uses `get_paths()` from `core/paths.py`. This creates inconsistency and will break if the working directory changes.

**9. `DEFAULT_MAX_CONCURRENCY` reads `os.getenv` directly.**  
`browser.py` line 84: `int(os.getenv("ENGINE_CONCURRENCY", "50"))` bypasses `get_settings()`. The settings object already has `engine_concurrency` and is the correct source.

### Low Priority

**10. Legacy frontend files not cleaned up.**  
`Frontend_Screenshot/src/index.js` and `src/services/apiService.js` are documented as "legacy" and "no longer loaded," but they remain in the repo. `ARCHITECTURE.md` notes they "can be deleted once the module system is verified complete" — that verification appears complete.

**11. Loose migration scripts at project root.**  
`migrate_app_url_db.py`, `migrate_city_db.py`, `reference_db_city_patch.py` are one-off scripts sitting at the repo root. They should either be converted to Alembic migrations or moved to a `scripts/` folder and documented.

**12. `backend_log.txt` committed to the repo.**  
Runtime log files should not be in version control. It should be added to `.gitignore`.

**13. `PPT_format/extracted/` raw XML in repo.**  
This looks like a reference extraction of a PPTX template. If it's used by `ppt_style_extractor.py`, the original `.pptx` is sufficient; the extracted XML is redundant and adds noise.

---

## Recommendations (Priority Order)

1. **Fix the JWT secret** — raise an error in production if `JWT_SECRET` is the default value.
2. **Lock CORS in production** — add a conditional in `main.py` based on `settings.app_env`.
3. **Split `browser.py`** — even a two-file split (helpers vs. orchestrator) would significantly improve maintainability.
4. **Delete dead code** — remove `_PASS1_PLACEMENT_JS_OLD` and the legacy frontend files.
5. **Replace `@app.on_event`** — migrate to lifespan context manager.
6. **Remove the startup ALTER TABLE guard** — rely on Alembic exclusively.
7. **Use `get_paths()` in `browser.py`** — consistent path handling across the codebase.
8. **Move test files into `tests/`** and add test coverage for the injection pipeline.
9. **Add `backend_log.txt` to `.gitignore`**.

---

## Dependency Snapshot

| Category | Library | Version |
|----------|---------|---------|
| API | FastAPI, Uvicorn | 0.111.0, 0.34.3 |
| Browser | Playwright | 1.58.0 |
| Database | SQLAlchemy, Alembic | 2.0.49, 1.13.1 |
| Auth | python-jose, bcrypt | 3.3.0, 4.2.1 |
| Reports | python-pptx, openpyxl, pandas | 1.0.2, 3.1.3, 2.2.2 |
| AI | Anthropic (optional) | not pinned |

All dependencies are pinned, which is good for reproducibility.

---

## Summary

This is a well-architected, production-grade tool with a clever two-pass injection engine and solid documentation. The main risks are the open JWT secret default, the open CORS config, and the `browser.py` monolith. Addressing those three would meaningfully improve security and maintainability without requiring a major refactor.
