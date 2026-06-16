# Ad Placement Engine - Core Extract

## Overview
This document describes the minimal, portable core engine for ad placement automation. Extract these files to use in any other project.

---

## Core Files to Extract

### 1. **services/image_utils.py** (Matching Algorithm)
- `get_local_creatives()` — Load ad images
- `find_best_match()` — Scoring algorithm
- `calculate_aspect_ratio_score()`
- `calculate_size_score()`
- `calculate_orientation_score()`
- `calculate_iab_match_score()`

**Purpose:** Multi-factor image-to-slot matching (0.0-1.0 score)

**Formula:**
```
Score = (Aspect Ratio × 0.40) + (Size × 0.30) + (Orientation × 0.20) + (IAB × 0.10)
Min Score: 0.40
```

---

### 2. **services/ad_detector.py** (Slot Detection)
- `detect_ad_slots(page)` — Async function
- DOM scanning with CSS selectors
- Position/dimension extraction
- Network request monitoring

**Purpose:** Identify advertising zones on pages

**Detects:**
- Google Ads (adsbygoogle, div-gpt-ad)
- Doubleclick, GPT, Taboola, Outbrain
- Custom CSS selectors
- IAB standard sizes (728×90, 300×250, 160×600, etc.)

---

### 3. **services/browser.py** (Orchestrator + Placement)
**Core Functions:**

- `open_website(urls, emit_cb)` — Main entry point (async)
- `process_single_url(context, url, creatives, lock, emit_cb, force_inject)` — Per-URL processor
- `apply_pass1_placement(page, slot, creative)` — In-slot injection
- `apply_natural_placement(page, creative, url)` — Fallback overlay
- `_enable_resource_blocking(page, block_ads)` — Performance optimization
- `close_popups(page)` — Consent/popup handling
- `remove_overlays(page)` — Modal/cookie banner removal
- `_is_security_verification_page(page)` — Cloudflare/bot-detection bypass
- `_navigate_with_retry(page, url)` — Robust navigation with backoff

**Two-Pass Strategy:**
```
PASS 1: Detect ad slots → Score creatives → Inject best match into slot
PASS 2: If creatives remain → Place naturally (sidebar/banner/inline)
```

**Key Variables:**
```python
PASS1_TOLERANCE = 35          # Strict pixel tolerance
PASS2_TOLERANCE = 99999       # Accept any size
DEFAULT_MAX_CONCURRENCY = 30  # Parallel URL processing
NAVIGATION_TIMEOUT_MS = 45000 # 45 seconds per page
```

---

### 4. **models/screenshot.py** (Data Model)
```python
class ScreenshotResult(Base):
    id: int
    url: str
    screenshot_path: str
    status: str  # success, skipped, failed, blocked, no_creative
    ads_found: int
    matches_found: int
    matched_creative_name: str
    matched_creative_size: str  # "728x90 (In-slot)"
    injection_type: str  # in-slot, overlay
    device: str  # Desktop, Mobile
    created_at: datetime
```

---

## Integration Pattern

### Step 1: Copy Files
```bash
# Minimal set (required)
cp services/image_utils.py    → your_project/
cp services/ad_detector.py    → your_project/
cp services/browser.py        → your_project/
cp models/screenshot.py       → your_project/

# Dependencies
pip install playwright playwright-stealth pillow sqlalchemy aiofiles
```

---

### Step 2: Initialize
```python
import asyncio
from browser import open_website

async def main():
    urls = [
        "https://example1.com",
        "https://example2.com",
    ]
    
    async def event_handler(event):
        """Handle progress events"""
        event_type = event.get("type")
        print(f"[EVENT] {event_type}: {event.get('payload')}")
    
    result = await open_website(
        urls=urls,
        emit_cb=event_handler
    )
    
    print(f"Success: {result['creatives_used']}/{result['creatives_total']}")
    for r in result['results']:
        print(f"  {r['url']}: {r['status']} ({r['image_used']})")

asyncio.run(main())
```

---

### Step 3: Emitted Events
Monitor progress via callback:

```python
{
    "type": "started",
    "payload": {"creatives": [...]}
}

{
    "type": "pass_start",
    "payload": {"pass_num": 1}
}

{
    "type": "site_start",
    "payload": {"url": "..."}
}

{
    "type": "site_loading",
    "payload": {"url": "..."}
}

{
    "type": "site_detecting",
    "payload": {}
}

{
    "type": "match_success",
    "payload": {
        "creative_name": "728x90-1.jpg",
        "url": "...",
        "dimensions": "728x90 (In-slot)"
    }
}

{
    "type": "creative_used",
    "payload": {
        "name": "728x90-1.jpg",
        "url": "..."
    }
}

{
    "type": "site_failed",
    "payload": {
        "url": "...",
        "pass_num": 1,
        "error": "..."
    }
}

{
    "type": "finished",
    "payload": {}
}
```

---

## Output Format

Each URL returns a result dict:
```python
{
    "url": "https://example.com",
    "domain": "example_com",
    "status": "success|skipped|failed|blocked|no_creative",
    
    # Condition Used (Pass 1 or Pass 2)
    "condition_used": 1 or 2,
    
    # Creative Placed
    "image_used": "728x90-1.jpg",
    "matched_size": "728x90 (In-slot)",
    
    # Placement Details
    "placement_zone": "top-banner|left-rail|inline",
    "placement_rule": "A|B|C",  # Pass 2 only
    "match_score": 0.85,  # Pass 1 only (0.0-1.0)
    
    # Output
    "screenshot_path": "screenshots/example_com.png",
    "notes": "Injection type: overlay"
}
```

---

## Configuration

### Environment Variables
```bash
# Navigation timeout (ms)
ENGINE_NAV_TIMEOUT_MS=45000

# Concurrent URLs
ENGINE_CONCURRENCY=30

# Scroll behavior
SCROLL_WAIT_MIN=150
SCROLL_WAIT_MAX=300
MAX_SCROLLS=4
```

### Tuning Parameters
In `browser.py`:
```python
INITIAL_PAGE_WAIT_MS       = 1500   # Page load settle time
SCROLL_WAIT_MIN_MS         = 150
SCROLL_WAIT_MAX_MS         = 300
POST_SCROLL_NETWORKIDLE_MS = 3000
POST_MASK_WAIT_MS          = 500    # After injection
ADDRESS_BAR_WAIT_MS        = 250
MAX_SCROLLS                = 4
NAV_MAX_RETRIES            = 3
```

### Blocking Rules
```python
# Always blocked (performance)
PERF_BLOCK_HINTS = (
    "google-analytics.com",
    "googletagmanager.com",
    "facebook.net",
    "hotjar.com",
    "clarity.ms",
)

# Blocked only in Pass 2
AD_NETWORK_HINTS = (
    "doubleclick.net",
    "googlesyndication.com",
)
```

---

## Scoring Algorithm Details

### Aspect Ratio (40% weight)
```
±5%:  1.0 (perfect)
±10%: 0.85
±25%: 0.60
±40%: 0.30
>40%: 0.0
```

### Size Match (30% weight)
```
0.8-1.2×: 1.0
Penalizes deviation
```

### Orientation (20% weight)
```
Vertical image + tall slot:   0.95
Horizontal image + wide slot: 0.95
Square image + square slot:   0.95
Square in any slot:           0.75
Mismatch:                     0.40
```

### IAB Bonus (10% weight)
```
Standard size (728×90, 300×250, etc.): +0.10
Non-standard: 0.0
```

---

## Error Handling

The engine includes:
- Navigation retry with exponential backoff (3 attempts)
- Security/bot-detection bypass (Cloudflare, reCAPTCHA)
- Popup/consent automation
- Network error recovery
- Screenshot validation
- Per-URL error isolation (one failure doesn't break others)
- Stealth mode (playwright-stealth)

---

## Advanced: Custom Ad Slot Selectors

Edit `services/ad_detector.py` → `CONFIG["selectors"]`:
```python
CONFIG = {
    "selectors": [
        'ins.adsbygoogle',
        '[id^="google_ads_iframe"]',
        '[id^="div-gpt-ad"]',
        # Add your custom selectors here:
        '.your-ad-class',
        '[data-ad-slot]',
        '#custom-banner',
    ],
}
```

---

## Performance Notes

- **Concurrency:** Default 30 URLs at a time (configurable)
- **Timeout:** 45 seconds per page (configurable)
- **Resource blocking:** Fonts, media, analytics disabled
- **Scrolling:** 4 lazy-load scrolls per page
- **Memory:** ~100-150MB per concurrent browser

---

## Compatibility

- **Python:** 3.10+
- **OS:** Windows, Linux, macOS
- **Browser:** Chromium (via Playwright)
- **Database:** Any SQLAlchemy-compatible DB (PostgreSQL, SQLite, MySQL)

---

## Limitations

1. Does NOT handle JavaScript frameworks that render ads post-load (React, Vue)
2. Does NOT bypass advanced bot detection (but retries)
3. Does NOT handle video ads or interactive creatives
4. Does NOT inject ads into iframes or shadow DOM
5. Does NOT detect A/B test variations

---

## Next Steps

1. Extract the 4 core files
2. Install dependencies: `pip install -r requirements.txt`
3. Place ad images in `input_images/` folder
4. Run `open_website(urls=[...], emit_cb=handler)`
5. Check results in database or returned dict
6. Export screenshots from `screenshots/` folder

