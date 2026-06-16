import asyncio
import json
import logging
import os
import random
import sys
import traceback
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Page, BrowserContext
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from services.ad_detector import detect_ad_slots, MUTATION_OBSERVER_SCRIPT
from services.db_service import save_screenshot_result
from services.screenshot_storage import save_screenshot_to_db as _save_to_ctr_db
from services.image_utils import find_best_match, get_local_creatives, get_creatives_for_domain, resize_creative_for_slot
from services.ppt_style_extractor import get_ppt_styles
from services.vision_detector import detect_ads_with_vision
from services.smart_placement import find_smart_placement

logger = logging.getLogger(__name__)

try:
    from playwright_stealth import stealth_async
except (ImportError, AttributeError):
    async def stealth_async(page: Page) -> None:
        return None


# Extra JS injected before every page load to mask Playwright/automation signals
_STEALTH_INIT_SCRIPT = """
() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'], configurable: true });
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const arr = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
            ];
            arr.__proto__ = PluginArray.prototype;
            return arr;
        },
        configurable: true,
    });
    if (window.chrome === undefined) { window.chrome = { runtime: {} }; }
    delete window.__playwright;
    delete window.__pw_manual;
    delete window.__PW_inspect;
}
"""


# Windows ProactorEventLoop is required for Playwright subprocesses
if sys.platform == "win32":
    try:
        if sys.version_info < (3, 14):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass


POPUP_TEXTS = [
    "Not Now", "No Thanks", "Close", "Dismiss",
    "Skip", "Maybe Later", "Continue Without Supporting",
    "Cancel", "Got It", "OK", "Okay", "Done",
    "Accept", "Reject All", "Decline",
    "Later", "Remind Me Later",
    "No", "I Agree", "Agree", "I Consent", "Consent",
    "Accept All", "Allow All", "Continue",
    "Don't Show Again", "Don't Ask Again",
]

INITIAL_PAGE_WAIT_MS       = 1500   # was 800 — ads need time to load after DOM ready
SCROLL_WAIT_MIN_MS         = 1000   # was 150 — let lazy-load triggers fire
SCROLL_WAIT_MAX_MS         = 2000   # was 300
POST_SCROLL_NETWORKIDLE_MS = 4500   # was 3000
POST_MASK_WAIT_MS          = 1500   # was 500 — wait after injection before screenshot
ADDRESS_BAR_WAIT_MS        = 250
MAX_SCROLLS                = 6      # was 4 — scroll further for below-fold ads
NAV_MAX_RETRIES            = 3
NAVIGATION_TIMEOUT_MS      = int(os.getenv("ENGINE_NAV_TIMEOUT_MS", "45000"))
DEFAULT_MAX_CONCURRENCY    = max(1, int(os.getenv("ENGINE_CONCURRENCY", "50")))

# Pass 1 — strict size match (must be < 50 to trigger the fast pixel-match path)
# 60px covers near-matches like 258x550 vs 300x600 (42px / 50px diff)
PASS1_TOLERANCE = 49
# Pass 2 — accept ANY slot size
PASS2_TOLERANCE = 99999

BLOCKED_RESOURCE_TYPES = {"font", "media", "manifest"}

# Analytics/trackers — always blocked
PERF_BLOCK_HINTS: tuple[str, ...] = (
    "google-analytics.com",
    "googletagmanager.com",
    "facebook.net",
    "hotjar.com",
    "clarity.ms",
)

# Ad networks — blocked only in Pass 2 (must load during Pass 1 detection)
AD_NETWORK_HINTS: tuple[str, ...] = (
    "doubleclick.net",
    "googlesyndication.com",
)


# ---------------------------------------------------------------------------
# Resource blocking
# ---------------------------------------------------------------------------

def _should_block_request(request, *, block_ads: bool = False) -> bool:
    if request.resource_type in BLOCKED_RESOURCE_TYPES:
        return True
    url = request.url.lower()
    if any(hint in url for hint in PERF_BLOCK_HINTS):
        return True
    if block_ads and any(hint in url for hint in AD_NETWORK_HINTS):
        return True
    return False


async def _enable_resource_blocking(page: Page, *, block_ads: bool = False) -> None:
    async def _route_handler(route):
        req = route.request
        if _should_block_request(req, block_ads=block_ads):
            await route.abort()
            return
        # Strip CSP headers from HTML document responses so injection JS is never blocked
        if req.resource_type == "document":
            try:
                response = await route.fetch()
                headers = {
                    k: v for k, v in response.headers.items()
                    if k.lower() not in (
                        "content-security-policy",
                        "content-security-policy-report-only",
                        "x-frame-options",
                    )
                }
                await route.fulfill(response=response, headers=headers)
                return
            except Exception:
                pass
        await route.continue_()
    await page.route("**/*", _route_handler)


# ---------------------------------------------------------------------------
# Network-based ad detection — CDN request interception
# ---------------------------------------------------------------------------

_AD_CDN_PATTERNS: tuple[str, ...] = (
    "doubleclick.net",
    "googlesyndication.com",
    "adnxs.com",
    "moatads.com",
    "amazon-adsystem.com",
    "media.net",
    "pubmatic.com",
    "rubiconproject.com",
    "openx.net",
    "taboola.com",
    "outbrain.com",
    "criteo.com",
    "adfit.kakao.com",
    "naver.com/adpost",
    "pagead2.googlesyndication.com",
)


def _setup_network_ad_intercept(page: Page) -> list:
    """
    Attach a lightweight request listener to the page.
    Returns a list that is populated with ad-CDN hit dicts as the page loads.
    These hits are later merged with DOM-detected slots to boost confidence.
    """
    ad_hits: list[dict] = []

    def _on_request(request) -> None:
        url = request.url.lower()
        for pattern in _AD_CDN_PATTERNS:
            if pattern in url:
                ad_hits.append({"url": request.url, "network": pattern})
                logger.debug("[NET] Ad CDN hit: %s → %s", pattern, request.url[:80])
                break

    page.on("request", _on_request)
    return ad_hits


# ---------------------------------------------------------------------------
# Popup / overlay helpers
# ---------------------------------------------------------------------------

async def close_popups(page: Page) -> None:
    """Try to close common popups by clicking known button texts."""
    for text in POPUP_TEXTS:
        try:
            locator = page.get_by_text(text, exact=True).first
            if await locator.is_visible(timeout=100):
                await locator.click(timeout=500)
                logger.info(f"[INFO] Closed popup: {text}")
                await page.wait_for_timeout(200)
                return
        except PlaywrightTimeoutError:
            pass
        except Exception as e:
            logger.info(f"[POPUP] Unexpected error checking '{text}': {e}")

    try:
        clicked = await page.evaluate(
            """() => {
                const labels = [
                    'i consent', 'accept all', 'accept', 'agree', 'i agree',
                    'allow all', 'continue', 'got it', 'ok', 'close'
                ];
                const controls = Array.from(document.querySelectorAll(
                    'button, [role="button"], input[type="button"], input[type="submit"], a'
                ));
                const target = controls.find((el) => {
                    const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().toLowerCase();
                    return labels.some((label) => text === label || text.includes(label));
                });
                if (target) { target.click(); return true; }
                return false;
            }"""
        )
        if clicked:
            logger.info("[INFO] Closed popup by consent fallback")
            await page.wait_for_timeout(300)
    except Exception as e:
        logger.info(f"[POPUP] Consent fallback error: {e}")


async def accept_consent(page: Page) -> None:
    """
    Accept GDPR/cookie consent banners so ad networks load their ads.
    Targets OneTrust, Quantcast, Cookiebot, and generic CMPs.
    Must be called BEFORE remove_overlays — accept first, then clean up.
    """
    # 1. Click known CMP accept buttons by selector
    cmp_accept_selectors = [
        # OneTrust
        "#onetrust-accept-btn-handler",
        ".onetrust-accept-btn-handler",
        # Quantcast
        ".qc-cmp2-summary-buttons button:last-child",
        # Cookiebot
        "#CybotCookiebotDialogBodyButtonAccept",
        # Generic accept buttons
        "[id*='accept-all']",
        "[class*='accept-all']",
        "[id*='cookie-accept']",
        "[class*='cookie-accept']",
        "button[data-action='accept']",
    ]
    for sel in cmp_accept_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=300):
                await btn.click(timeout=500)
                await page.wait_for_timeout(600)
                logger.info("[CONSENT] Accepted via %s", sel)
                return
        except Exception:
            pass

    # 2. Text-based accept — catch remaining CMPs
    accept_texts = [
        "Accept All", "Accept all", "Accept All Cookies",
        "Agree & Proceed", "I Accept", "Allow All",
        "OK, I Agree", "Got It", "I Agree",
        "Consent", "Continue", "Agree",
    ]
    for text in accept_texts:
        try:
            btn = page.get_by_role("button", name=text, exact=False).first
            if await btn.is_visible(timeout=200):
                await btn.click(timeout=400)
                await page.wait_for_timeout(500)
                logger.info("[CONSENT] Accepted via text '%s'", text)
                return
        except Exception:
            pass


async def remove_overlays(page: Page) -> None:
    """Remove residual overlay/modal elements after consent is handled."""
    try:
        await page.evaluate(
            """() => {
                const selectors = [
                    '.modal', '.popup',
                    '.newsletter', '.subscribe',
                    '[id*="cookie"]', '[id*="consent"]',
                    '[class*="cookie-banner"]', '[class*="consent-banner"]',
                    '[class*="gdpr"]', '[class*="cmp-"]',
                    '[id*="popup"]', '[class*="popup"]',
                    '[aria-modal="true"]', '[role="dialog"]'
                ];
                selectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => {
                        // Only remove if it looks like a blocking overlay
                        const style = window.getComputedStyle(el);
                        const isFixed = style.position === 'fixed' ||
                                        style.position === 'sticky';
                        const coversPage = el.getBoundingClientRect().width >
                                           window.innerWidth * 0.5;
                        if (isFixed && coversPage) el.remove();
                    });
                });
                document.body.style.overflow = 'auto';
                document.documentElement.style.overflow = 'auto';
            }"""
        )
    except Exception as e:
        logger.info(f"[OVERLAY] remove_overlays error: {e}")


# ---------------------------------------------------------------------------
# Security / bot-challenge detection
# ---------------------------------------------------------------------------

async def _is_security_verification_page(page: Page) -> bool:
    try:
        return await page.evaluate(
            """() => {
                const title = (document.title || '').toLowerCase();
                const bodyText = (document.body?.innerText || '').toLowerCase().substring(0, 3000);

                const titleKeywords = [
                    'just a moment', 'attention required', 'access denied',
                    'security check', 'please wait', 'checking your browser',
                    'verify you are human', 'bot verification', 'ddos protection',
                    'are you a robot', 'pardon our interruption'
                ];
                for (const kw of titleKeywords) {
                    if (title.includes(kw)) return true;
                }

                const bodyKeywords = [
                    'checking your browser before accessing',
                    'this process is automatic',
                    'verify you are human',
                    'please enable cookies',
                    'ray id:', 'cloudflare',
                    'performing a security check',
                    'please stand by',
                    'access to this page has been denied',
                    'please complete the security check',
                    "you don't have permission to access",
                    'errors.edgesuite.net',
                    'edgesuite',
                    'akamai',
                    'reference #'
                ];
                for (const kw of bodyKeywords) {
                    if (bodyText.includes(kw)) return true;
                }

                const challengeSelectors = [
                    'iframe[src*="challenges.cloudflare.com"]',
                    'iframe[src*="recaptcha"]',
                    'iframe[src*="hcaptcha"]',
                    '.cf-browser-verification',
                    '#challenge-form',
                    '#cf-challenge-running',
                    '.g-recaptcha',
                    '.h-captcha',
                    '#px-captcha'
                ];
                for (const sel of challengeSelectors) {
                    if (document.querySelector(sel)) return true;
                }

                return false;
            }"""
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Navigation with retry + exponential backoff
# ---------------------------------------------------------------------------

async def _navigate_with_retry(page: Page, url: str) -> None:
    last_error: Exception | None = None

    for attempt in range(NAV_MAX_RETRIES):
        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
            return
        except Exception as e:
            last_error = e
            logger.warning(f"[WARN] Navigation attempt {attempt + 1}/{NAV_MAX_RETRIES} failed for {url}: {e}")
            if attempt < NAV_MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)

    try:
        logger.warning(f"[WARN] Trying commit-level fallback for {url}")
        await page.goto(url, wait_until="commit", timeout=NAVIGATION_TIMEOUT_MS)
    except Exception as fallback_error:
        logger.warning(f"[WARN] Commit fallback also failed for {url}: {fallback_error}")


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------

async def _wait_for_ads_to_render(page: Page, timeout_ms: int = 5000) -> None:
    """
    Polls until at least one known ad container has non-zero dimensions,
    or until timeout. This ensures GPT/DFP iframes have loaded before we scan.
    """
    poll_interval = 300
    elapsed = 0
    while elapsed < timeout_ms:
        try:
            has_ads = await page.evaluate("""() => {
                const gptDivs = document.querySelectorAll(
                    '[id^="div-gpt-ad"], [id*="gpt-ad"], ins.adsbygoogle'
                );
                for (const el of gptDivs) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 10 && rect.height > 10) return true;
                    const iframe = el.querySelector('iframe');
                    if (iframe) {
                        const fr = iframe.getBoundingClientRect();
                        if (fr.width > 10 && fr.height > 10) return true;
                    }
                }
                return false;
            }""")
            if has_ads:
                logger.info("[ENGINE] Ad slots rendered (%.0fms)", elapsed)
                return
        except Exception:
            pass
        await page.wait_for_timeout(poll_interval)
        elapsed += poll_interval
    logger.info("[ENGINE] Ad render wait timed out after %dms — scanning anyway", timeout_ms)


async def _scroll_and_collect_slots(page: Page) -> list:
    """
    Scroll through the full page in steps, running ad detection at each position.
    Returns deduplicated list of all ad slots found across all scroll positions.
    Catches lazy-loaded ads that only render when scrolled into view.
    """
    all_slots: list[dict] = []

    def _is_duplicate(slot: dict, existing: list) -> bool:
        for s in existing:
            if (abs(s["x"] - slot["x"]) < 10 and
                    abs(s["y"] - slot["y"]) < 10 and
                    abs(s["width"]  - slot["width"])  < 10 and
                    abs(s["height"] - slot["height"]) < 10):
                return True
        return False

    scroll_y = 0
    viewport_h = 900
    try:
        page_h = await page.evaluate(
            "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
        )
    except Exception:
        page_h = 3000

    step = 600
    max_steps = 8   # cap at 8 scroll positions to keep scan fast

    for _ in range(max_steps):
        await page.evaluate(f"window.scrollTo(0, {scroll_y})")
        await page.wait_for_timeout(400)
        try:
            result = await detect_ad_slots(page)
            for slot in result.get("slots", []):
                if not _is_duplicate(slot, all_slots):
                    all_slots.append(slot)
        except Exception:
            pass
        scroll_y += step
        if scroll_y >= page_h:
            break

    # Scroll back to top
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(200)

    logger.info("[ENGINE] Scroll-detect: %d unique slots across page", len(all_slots))
    return all_slots


async def _scroll_page(page: Page) -> None:
    current_position = 0
    scrolls = 0
    while scrolls < MAX_SCROLLS:
        current_position += random.randint(600, 1000)
        await page.evaluate(f"window.scrollTo(0, {current_position})")
        await page.wait_for_timeout(random.randint(SCROLL_WAIT_MIN_MS, SCROLL_WAIT_MAX_MS))
        new_height = await page.evaluate(
            "() => Math.max(document.body?.scrollHeight || 0, document.documentElement?.scrollHeight || 0)"
        )
        if not new_height or current_position >= new_height:
            break
        scrolls += 1

    try:
        await page.wait_for_load_state("networkidle", timeout=POST_SCROLL_NETWORKIDLE_MS)
    except Exception:
        pass


async def _take_screenshot(page: Page, path: str) -> str:
    """Takes a viewport screenshot; returns path on success or '' on failure."""
    try:
        await page.screenshot(path=path, full_page=False)
        logger.info(f"[SCREENSHOT] Saved: {path}")
        return path
    except Exception as e:
        logger.info(f"[SCREENSHOT ERROR] {path}: {e}")
        return ""


async def _take_injection_screenshot(
    page: Page,
    path: str,
    slot_x: int,
    slot_y: int,
    slot_w: int,
    slot_h: int,
    padding: int = 120,
) -> str:
    """
    Takes a focused screenshot centred on the injected creative.

    Strategy:
    1. Scroll the page so the slot is vertically centred in the viewport.
    2. Take a full-viewport screenshot (captures surrounding page context).
    3. Crop the image to a region that puts the creative prominently in
       the frame — context padding on all sides so the page environment
       is still visible, but the ad fills ~40 % of the output image.
    """
    try:
        from PIL import Image as _PILImage
        import io as _io

        vp = page.viewport_size or {"width": 1440, "height": 900}
        vp_w, vp_h = vp["width"], vp["height"]

        ADDRESS_BAR_H = 48

        # Scroll so the injected slot is vertically centred in the viewport.
        # We keep the full viewport width — this shows the ad naturally in
        # the page layout, like a real browser screenshot.
        center_y = slot_y + slot_h // 2
        scroll_y = max(0, center_y - (vp_h - ADDRESS_BAR_H) // 2 - ADDRESS_BAR_H)
        await page.evaluate(f"window.scrollTo(0, {scroll_y})")
        await page.wait_for_timeout(800)

        # Full viewport screenshot — no cropping, full page width visible
        raw_bytes = await page.screenshot(full_page=False)
        img = _PILImage.open(_io.BytesIO(raw_bytes))
        img.save(path)
        logger.info("[SCREENSHOT] Full-viewport screenshot saved (slot centred): %s", path)

        return path

    except Exception as e:
        logger.warning("[SCREENSHOT] Focused screenshot failed (%s): %s — falling back", path, e)
        return await _take_screenshot(page, path)


async def _save_to_db(
    *,
    url: str,
    final_image_path: str,
    ad_slots: list,
    matches_count: int,
    matched_name: str | None,
    matched_size: str | None,
    injection_type: str | None,
    viewport,
    original_image_path: str | None = None,
    scan_job_id: str | None = None,
    match_score: float | None = None,
) -> None:
    device_type = "Mobile" if viewport and viewport.get("width", 1440) < 600 else "Desktop"

    # ── scanner.db (existing) ─────────────────────────────────────────────
    await asyncio.to_thread(
        save_screenshot_result,
        website=url,
        image_path=final_image_path,
        status="success",
        ads_found=len(ad_slots) if ad_slots else 0,
        matches_found=matches_count,
        matched_creative_name=matched_name,
        matched_creative_size=matched_size,
        injection_type=injection_type,
        device=device_type,
    )

    # ── ctr_db: save binary screenshots ───────────────────────────────────
    try:
        domain = urlparse(url).netloc
        await asyncio.to_thread(
            _save_to_ctr_db,
            url=url,
            domain=domain,
            device=device_type,
            status="success",
            screenshot_path=final_image_path,
            original_path=original_image_path,
            scan_job_id=scan_job_id,
            ads_found=len(ad_slots) if ad_slots else 0,
            slots_injected=matches_count,
            creative_name=matched_name,
            creative_size=matched_size,
            injection_type=injection_type,
            match_score=match_score,
        )
    except Exception as _ctr_err:
        logger.warning("[CTR-DB] Failed to save screenshot for %s: %s", url, _ctr_err)


# ---------------------------------------------------------------------------
# JavaScript constants — all dynamic values passed as args, never f-stringed
# ---------------------------------------------------------------------------

_ADDRESS_BAR_JS = """
(displayUrl) => {
    const existing = document.getElementById('mock-address-bar');
    if (existing) existing.remove();

    const bar = document.createElement('div');
    bar.id = 'mock-address-bar';
    bar.style.cssText = 'position:fixed!important;top:0!important;left:0!important;width:100%!important;height:48px!important;background-color:#2b2b36!important;border-bottom:1px solid #1c1c24!important;z-index:2147483647!important;display:flex!important;align-items:center!important;padding:0 16px!important;box-sizing:border-box!important;gap:12px!important;';

    const leftGroup = document.createElement('div');
    leftGroup.style.cssText = 'display:flex!important;align-items:center!important;gap:16px!important;margin-right:16px!important;';
    leftGroup.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" style="cursor:pointer!important;">
            <path d="M12.5 8H3.5M3.5 8L7.5 4M3.5 8L7.5 12" stroke="#e3e3e8" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" style="cursor:default!important;opacity:0.45;">
            <path d="M3.5 8H12.5M12.5 8L8.5 4M12.5 8L8.5 12" stroke="#e3e3e8" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" style="cursor:pointer!important;">
            <path d="M13.65 2.35A7.95 7.95 0 0 0 8 0a8 8 0 1 0 8 8h-2a6 6 0 1 1-6-6c1.66 0 3.14.69 4.22 1.78L10 6h6V0l-2.35 2.35z" fill="#e3e3e8"/>
        </svg>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" style="cursor:pointer!important;">
            <path d="M2.5 6.5l5.5-4.5 5.5 4.5v6.5a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1v-6.5z" stroke="#e3e3e8" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M5.5 13V8.5h5V13" stroke="#e3e3e8" stroke-width="1.5" stroke-linejoin="round"/>
        </svg>
    `;
    bar.appendChild(leftGroup);

    const urlBar = document.createElement('div');
    urlBar.style.cssText = 'flex:1!important;height:32px!important;background-color:#1e1e28!important;border-radius:20px!important;display:flex!important;align-items:center!important;padding:0 12px!important;box-sizing:border-box!important;margin-right:16px!important;';
    urlBar.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" style="margin-right:10px;cursor:pointer!important;">
            <path d="M3 5.5h10M3 10.5h10" stroke="#e3e3e8" stroke-width="1.5" stroke-linecap="round"/>
            <circle cx="5.5" cy="5.5" r="1.75" fill="#1e1e28" stroke="#e3e3e8" stroke-width="1.5"/>
            <circle cx="10.5" cy="10.5" r="1.75" fill="#1e1e28" stroke="#e3e3e8" stroke-width="1.5"/>
        </svg>
        <div style="flex:1!important;color:#e3e3e8!important;font-size:13px!important;font-weight:400!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;margin-right:12px!important;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif!important;">${displayUrl}</div>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" style="margin-right:12px;cursor:pointer!important;opacity:0.85;">
            <circle cx="7" cy="7" r="4.5" stroke="#e3e3e8" stroke-width="1.5"/>
            <line x1="10.5" y1="10.5" x2="14" y2="14" stroke="#e3e3e8" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" style="cursor:pointer!important;opacity:0.85;">
            <path d="M8 1.5l1.9 3.9 4.3.6-3.1 3 1 4.3-4.1-2.1-4.1 2.1 1-4.3-3.1-3 4.3-.6L8 1.5z" stroke="#e3e3e8" stroke-width="1.5" stroke-linejoin="round" fill="none"/>
        </svg>
    `;
    bar.appendChild(urlBar);

    const rightGroup = document.createElement('div');
    rightGroup.style.cssText = 'display:flex!important;align-items:center!important;gap:14px!important;';
    rightGroup.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" style="cursor:pointer!important;">
            <path d="M9 2a2 2 0 0 1 2 2v1h2.5A1.5 1.5 0 0 1 16 6.5V9h1a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-1v2.5A1.5 1.5 0 0 1 14.5 17H12v-1a2 2 0 0 0-2-2 2 2 0 0 0-2 2v1H5.5A1.5 1.5 0 0 1 4 15.5V13h1a2 2 0 0 0 2-2 2 2 0 0 0-2-2H4V6.5A1.5 1.5 0 0 1 5.5 5H8V4a2 2 0 0 1 2-2z" stroke="#e3e3e8" stroke-width="1.5" stroke-linejoin="round"/>
        </svg>
        <div style="width:1px!important;height:16px!important;background-color:#4a4a5a!important;"></div>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#e3e3e8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="cursor:pointer!important;">
            <rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect>
            <line x1="12" y1="18" x2="12.01" y2="18"></line>
        </svg>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#e3e3e8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="cursor:pointer!important;">
            <polyline points="16 18 22 12 16 6"></polyline>
            <polyline points="8 6 2 12 8 18"></polyline>
        </svg>
        <div style="width:1px!important;height:16px!important;background-color:#4a4a5a!important;"></div>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#e3e3e8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="cursor:pointer!important;">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
        </svg>
        <div style="display:flex!important;align-items:center!important;gap:6px!important;padding:4px 12px 4px 6px!important;background-color:#0b57d0!important;border-radius:100px!important;color:#ffffff!important;font-size:12px!important;font-weight:500!important;cursor:pointer!important;height:24px!important;box-sizing:border-box!important;">
            <div style="width:16px!important;height:16px!important;background-color:#ffffff!important;border-radius:50%!important;display:flex!important;align-items:center!important;justify-content:center!important;font-size:10px!important;font-weight:700!important;color:#0b57d0!important;line-height:1!important;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif!important;">W</div>
            <span style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif!important;">Work</span>
        </div>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#e3e3e8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="cursor:pointer!important;">
            <circle cx="12" cy="12" r="1.5"></circle>
            <circle cx="12" cy="5" r="1.5"></circle>
            <circle cx="12" cy="19" r="1.5"></circle>
        </svg>
    `;
    bar.appendChild(rightGroup);
    document.body.appendChild(bar);
}
"""

_NATURAL_PLACEMENT_JS = """
([c_w, c_h, base64, is_vertical]) => {
    document.querySelectorAll('.automation-overlay-container').forEach(el => el.remove());
    const oldStyle = document.getElementById('__ad_pass2_b_style__');
    if (oldStyle) oldStyle.remove();

    const SPACING = 16;
    const HEADER_HEIGHT = 48;

    const adSelectors = [
        'ins.adsbygoogle', '[id^="google_ads_iframe"]', '[id^="div-gpt-ad"]',
        '[class*="ad-unit"]', '[id*="ad-unit"]', '.ad-container', '.ad-slot',
        'iframe[src*="doubleclick.net"]', 'iframe[src*="googlesyndication.com"]',
        'iframe[id^="ads-"]',
        '[class*="adBox"]', '[class*="ad-box"]', '[class*="AdBox"]',
        '[class*="leaderboard"]', '[class*="billboard"]',
        '[class*="ad_"]', '[id*="ad_"]', '[class*="_ad"]',
        '[data-ad-unit]', '[data-ad]',
        'div[style*="width:728px"]', 'div[style*="width: 728px"]'
    ];
    document.querySelectorAll(adSelectors.join(', ')).forEach(el => {
        el.style.setProperty('display', 'none', 'important');
        el.style.setProperty('visibility', 'hidden', 'important');
        el.style.setProperty('height', '0', 'important');
        el.style.setProperty('min-height', '0', 'important');
        el.style.setProperty('overflow', 'hidden', 'important');

        let parent = el.parentElement;
        while (parent && parent !== document.body) {
            const kids = Array.from(parent.children);
            const allHidden = kids.every(k =>
                k.style.display === 'none' ||
                k.style.visibility === 'hidden' ||
                k.getBoundingClientRect().height === 0
            );
            if (allHidden) {
                parent.style.setProperty('display', 'none', 'important');
                parent = parent.parentElement;
            } else {
                break;
            }
        }
    });

    if (!is_vertical) {
        const NAV_SELECTORS = [
            '[class*="ipc-page-header"]',
            '[class*="NavBar"]',
            '[class*="navbar"]',
            '[data-testid="header"]',
            'header nav',
            'nav[role="navigation"]',
            '[role="navigation"]',
            'nav',
            'header',
            '.navbar',
            '.nav-bar',
            '.site-header',
            '.header',
            '#header',
            '#navbar',
            '#nav',
            '#site-header'
        ];
        let navEl = null;
        for (let i = 0; i < NAV_SELECTORS.length; i++) {
            const candidates = document.querySelectorAll(NAV_SELECTORS[i]);
            for (let j = 0; j < candidates.length; j++) {
                const rect = candidates[j].getBoundingClientRect();
                if (rect.height > 0) {
                    if (!navEl || rect.bottom > navEl.getBoundingClientRect().bottom) {
                        navEl = candidates[j];
                    }
                }
            }
            if (navEl) break;
        }

        const banner = document.createElement('div');
        banner.className = 'automation-overlay-container';
        banner.style.cssText = [
            'display:flex!important',
            'align-items:center!important',
            'justify-content:center!important',
            'width:100%!important',
            'height:' + c_h + 'px!important',
            'overflow:visible!important',
            'position:relative!important',
            'box-sizing:border-box!important',
            'margin:0!important',
            'padding:0!important',
            'background:transparent!important',
            'z-index:8999!important'
        ].join(';');

        const img = document.createElement('img');
        img.src = base64;
        // Exact uploaded dimensions — no scaling, no object-fit, no constraints
        img.style.cssText = [
            'display:block!important',
            'width:' + c_w + 'px!important',
            'height:' + c_h + 'px!important',
            'min-width:' + c_w + 'px!important',
            'min-height:' + c_h + 'px!important',
            'max-width:none!important',
            'max-height:none!important',
            'flex-shrink:0!important',
            'margin:0!important',
            'padding:0!important',
            'border:none!important',
            'pointer-events:none!important'
        ].join(';');
        banner.appendChild(img);

        const bodyChildren = Array.from(document.body.children);
        let insertTarget = null;

        for (const child of bodyChildren) {
            const tag = child.tagName.toLowerCase();
            const cls = (child.className || '').toLowerCase();
            const id  = (child.id || '').toLowerCase();

            const isNav = tag === 'nav' || tag === 'header' ||
                          cls.includes('header') || cls.includes('nav') ||
                          id.includes('header') || id.includes('nav') ||
                          child.getAttribute('role') === 'navigation';

            if (!isNav && child.getBoundingClientRect().height > 0) {
                insertTarget = child;
                break;
            }
        }

        if (insertTarget) {
            document.body.insertBefore(banner, insertTarget);
        } else if (navEl && navEl.parentNode) {
            navEl.parentNode.insertBefore(banner, navEl.nextSibling);
        } else {
            document.body.insertBefore(banner, document.body.firstChild);
        }

        const bannerH = banner.getBoundingClientRect().height || c_h;
        const gap = bannerH + 4;
        const style = document.createElement('style');
        style.id = '__ad_pass2_b_style__';
        style.textContent = [
            'body > main',
            'body > [role="main"]',
            'body > .main',
            'body > #main',
            'body > .main-content',
            'body > #main-content',
            'body > .page-content',
            'body > #page-content',
            'body > .wrapper',
            'body > #wrapper',
            'body > .container',
            'body > #container',
            'body > .content-wrap',
            'body > .site-content',
            'body > #site-content',
            'body > article',
            'body > section'
        ].join(',') + ' { margin-top: ' + gap + 'px !important; box-sizing: border-box !important; }';
        document.head.appendChild(style);

        console.log('[NATURAL] Horizontal banner: creative=' + c_w + 'x' + c_h + ', strip height=' + bannerH + ', content gap=' + gap + 'px');
        return true;

    } else {
        // Detect whether to place on RIGHT or LEFT.
        // Check if the page already has a right-side ad column.
        const pageW = document.documentElement.scrollWidth || window.innerWidth;
        const rightThreshold = pageW * 0.6;
        const rightAdSelectors = [
            '[id^="div-gpt-ad"]', '[id*="gpt-ad"]', 'ins.adsbygoogle',
            '[class*="adBox"]', '[class*="ad-unit"]', '[class*="sidebar-ad"]',
            '[class*="adBlock"]', '[class*="advertisement"]'
        ];
        let hasRightAd = false;
        for (const sel of rightAdSelectors) {
            document.querySelectorAll(sel).forEach(el => {
                const r = el.getBoundingClientRect();
                const iframe = el.querySelector('iframe');
                const w = (r.width > 10) ? r.width : (iframe ? iframe.getBoundingClientRect().width : 0);
                const x = r.left + window.scrollX;
                if (w > 10 && x > rightThreshold) hasRightAd = true;
            });
        }

        const useRight = hasRightAd;
        const gutterPos = useRight ? 'right:0!important' : 'left:0!important';
        const borderSide = useRight ? 'border-left:1px solid #d8d8d8!important' : 'border-right:1px solid #d8d8d8!important';

        const gutter = document.createElement('div');
        gutter.className = 'automation-overlay-container';
        gutter.style.cssText = [
            'position:fixed!important',
            'top:0!important',
            gutterPos,
            'width:' + (c_w + SPACING * 2) + 'px!important',
            'height:100vh!important',
            'background:#f0f0f0!important',
            borderSide,
            'z-index:2147483644!important',
            'pointer-events:none!important'
        ].join(';');
        document.body.appendChild(gutter);

        const containerPos = useRight
            ? 'right:' + SPACING + 'px!important'
            : 'left:' + SPACING + 'px!important';

        const container = document.createElement('div');
        container.className = 'automation-overlay-container';
        container.style.cssText = [
            'position:fixed!important',
            'top:' + (HEADER_HEIGHT + SPACING) + 'px!important',
            containerPos,
            'width:' + c_w + 'px!important',
            'height:' + c_h + 'px!important',
            'z-index:2147483646!important',
            'display:flex!important',
            'align-items:center!important',
            'justify-content:center!important',
            'pointer-events:none!important',
            'box-shadow:0 2px 12px rgba(0,0,0,0.15)!important',
            'border-radius:4px!important',
            'overflow:hidden!important',
            'background:#ffffff!important'
        ].join(';');

        const img = document.createElement('img');
        img.src = base64;
        // Exact uploaded dimensions — no scaling, no object-fit, no constraints
        img.style.cssText = [
            'width:' + c_w + 'px!important',
            'height:' + c_h + 'px!important',
            'min-width:' + c_w + 'px!important',
            'min-height:' + c_h + 'px!important',
            'max-width:none!important',
            'max-height:none!important',
            'display:block!important',
            'pointer-events:none!important'
        ].join(';');
        container.appendChild(img);
        document.body.appendChild(container);

        const rootSelectors = [
            '#root', '#app', '#__next', '#main', 'main',
            '[role="main"]', '.wrapper', '#wrapper',
            '.container', '#container', '.site-wrapper',
            '.page-wrapper', '#page-wrapper'
        ];
        let rootEl = null;
        for (const sel of rootSelectors) {
            const el = document.querySelector(sel);
            if (el) { rootEl = el; break; }
        }

        // Only push content over when placing on the LEFT;
        // right-side placement overlaps the existing ad column so no shift needed.
        if (!useRight) {
            const shiftPx = c_w + SPACING * 2 + 8;
            if (rootEl) {
                rootEl.style.setProperty('margin-left', shiftPx + 'px', 'important');
                rootEl.style.setProperty('box-sizing', 'border-box', 'important');
            } else {
                document.body.style.setProperty('margin-left', shiftPx + 'px', 'important');
            }
        }

        console.log('[NATURAL] Vertical sidebar (' + (useRight ? 'right' : 'left') + '): creative=' + c_w + 'x' + c_h);
        return true;
    }
}
"""

_MOBILE_ADDRESS_BAR_JS = """
(displayUrl) => {
    const existing = document.getElementById('mock-address-bar');
    if (existing) existing.remove();

    const bar = document.createElement('div');
    bar.id = 'mock-address-bar';
    bar.style.cssText = [
        'position:fixed!important',
        'top:0!important',
        'left:0!important',
        'width:100%!important',
        'height:52px!important',
        'background:#1c1c1e!important',
        'z-index:2147483647!important',
        'display:flex!important',
        'flex-direction:column!important',
        'align-items:stretch!important',
        'box-sizing:border-box!important',
        'padding:8px 12px 6px!important',
        'gap:0!important',
    ].join(';');

    // Status bar row (time + icons)
    const statusBar = document.createElement('div');
    statusBar.style.cssText = 'display:flex!important;justify-content:space-between!important;align-items:center!important;height:14px!important;margin-bottom:6px!important;padding:0 2px!important;';
    statusBar.innerHTML = `
        <span style="color:#fff;font-size:11px;font-weight:600;font-family:-apple-system,sans-serif;">9:41</span>
        <div style="display:flex;gap:5px;align-items:center;">
            <svg width="16" height="10" viewBox="0 0 16 10" fill="none"><rect x="0" y="3" width="3" height="7" rx="0.5" fill="white" opacity="0.4"/><rect x="4" y="2" width="3" height="8" rx="0.5" fill="white" opacity="0.6"/><rect x="8" y="1" width="3" height="9" rx="0.5" fill="white" opacity="0.8"/><rect x="12" y="0" width="3" height="10" rx="0.5" fill="white"/></svg>
            <svg width="15" height="11" viewBox="0 0 15 11" fill="white"><path d="M7.5 2.2C9.8 2.2 11.9 3.1 13.4 4.6L14.8 3.2C12.9 1.2 10.3 0 7.5 0S2.1 1.2 0.2 3.2L1.6 4.6C3.1 3.1 5.2 2.2 7.5 2.2Z" opacity="0.4"/><path d="M7.5 5C8.9 5 10.2 5.6 11.1 6.5L12.5 5.1C11.2 3.8 9.4 3 7.5 3S3.8 3.8 2.5 5.1L3.9 6.5C4.8 5.6 6.1 5 7.5 5Z" opacity="0.7"/><circle cx="7.5" cy="9" r="2" fill="white"/></svg>
            <div style="display:flex;gap:1px;align-items:center;"><div style="width:22px;height:11px;border:1.5px solid rgba(255,255,255,0.6);border-radius:2.5px;padding:1.5px;box-sizing:border-box;"><div style="background:white;border-radius:1px;height:100%;width:85%;"></div></div><div style="width:2px;height:5px;background:rgba(255,255,255,0.5);border-radius:0 1px 1px 0;margin-left:1px;"></div></div>
        </div>
    `;
    bar.appendChild(statusBar);

    // URL pill
    const pill = document.createElement('div');
    pill.style.cssText = [
        'display:flex!important',
        'align-items:center!important',
        'background:#3a3a3c!important',
        'border-radius:10px!important',
        'height:28px!important',
        'padding:0 10px!important',
        'box-sizing:border-box!important',
        'gap:6px!important',
    ].join(';');
    pill.innerHTML = `
        <svg width="11" height="13" viewBox="0 0 11 13" fill="none"><path d="M5.5 0C3.6 0 2 1.6 2 3.5V4H1C0.4 4 0 4.4 0 5v7c0 .6.4 1 1 1h9c.6 0 1-.4 1-1V5c0-.6-.4-1-1-1H9V3.5C9 1.6 7.4 0 5.5 0zm0 1.5C6.6 1.5 7.5 2.4 7.5 3.5V4h-4V3.5C3.5 2.4 4.4 1.5 5.5 1.5z" fill="rgba(255,255,255,0.6)"/></svg>
        <span style="flex:1;color:rgba(255,255,255,0.85);font-size:12px;font-weight:400;font-family:-apple-system,sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:center;">${displayUrl}</span>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><circle cx="5" cy="5" r="4" stroke="rgba(255,255,255,0.5)" stroke-width="1.3"/><line x1="8" y1="8" x2="11" y2="11" stroke="rgba(255,255,255,0.5)" stroke-width="1.3" stroke-linecap="round"/></svg>
    `;
    bar.appendChild(pill);

    document.body.appendChild(bar);
}
"""

_PASS1_PLACEMENT_JS = """
([x, y, selector, c_w, c_h, slot_w, slot_h, base64]) => {
    // ── OVERLAY APPROACH ─────────────────────────────────────────────────────
    // Instead of replacing content inside the ad container (which Google's GPT
    // re-fires and overwrites), we:
    //   1. Find the real ad element and hide it (opacity:0 keeps the slot alive
    //      so GPT doesn't detect a missing slot and re-trigger).
    //   2. Drop an absolutely-positioned overlay div onto document.body with
    //      our creative on top. Google can never touch body-level elements.
    // ─────────────────────────────────────────────────────────────────────────

    const w = c_w;
    const h = c_h;

    // ── Step 1: Find the ad element to hide ─────────────────────────────
    const findContainer = () => {
        // Pass A: CSS selector closest to slot coords
        const cleanSel = (selector || '').replace(/\\s*\\([^)]*\\)\\s*$/, '').trim();
        if (cleanSel) {
            try {
                let best = null, bestDiff = 999;
                document.querySelectorAll(cleanSel).forEach(el => {
                    const r = el.getBoundingClientRect();
                    const diff = Math.abs(r.left + window.scrollX - x) +
                                 Math.abs(r.top  + window.scrollY - y);
                    if (diff < bestDiff) { bestDiff = diff; best = el; }
                });
                if (best && bestDiff < 250) {
                    console.log('[INJECT] Found via selector diff=' + bestDiff);
                    return best;
                }
            } catch(e) {}
        }
        // Pass B: elementFromPoint — sample 3 points inside the slot
        const vpX = x - window.scrollX;
        const vpY = y - window.scrollY;
        if (vpX >= 0 && vpY >= 0 && vpX < window.innerWidth && vpY < window.innerHeight) {
            const points = [
                [vpX + slot_w * 0.5, vpY + slot_h * 0.5],
                [vpX + slot_w * 0.5, vpY + slot_h * 0.25],
                [vpX + slot_w * 0.25, vpY + slot_h * 0.5],
            ];
            for (const [px, py] of points) {
                const hit = document.elementFromPoint(px, py);
                if (!hit || hit === document.body || hit === document.documentElement) continue;
                let el = hit, bestAdEl = null;
                for (let i = 0; i < 10; i++) {
                    if (!el || el === document.body) break;
                    const id  = (el.id || '').toLowerCase();
                    const cls = typeof el.className === 'string' ? el.className.toLowerCase() : '';
                    if (el.tagName === 'INS' ||
                        id.includes('ad') || id.includes('gpt') || id.includes('banner') ||
                        cls.includes('ad') || cls.includes('sponsor') || cls.includes('banner') ||
                        el.getAttribute('data-ad-slot') || el.getAttribute('data-google-query-id') ||
                        el.getAttribute('data-ad-unit-path')) {
                        bestAdEl = el;
                    }
                    el = el.parentElement;
                }
                if (bestAdEl) {
                    console.log('[INJECT] Found via point-walk: ' + bestAdEl.tagName + '#' + bestAdEl.id);
                    return bestAdEl;
                }
                const r = hit.getBoundingClientRect();
                if (r.width > 40 && r.height > 20) return hit;
            }
        }
        // Pass C: proximity fallback — any element near coords with matching size
        let best = null, bestDiff = 250;
        document.querySelectorAll('*').forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width < 10 || r.height < 10) return;
            const diff = Math.abs(r.left + window.scrollX - x) +
                         Math.abs(r.top  + window.scrollY - y);
            if (diff < bestDiff &&
                Math.abs(r.width  - slot_w) < 120 &&
                Math.abs(r.height - slot_h) < 120) {
                bestDiff = diff; best = el;
            }
        });
        if (best) console.log('[INJECT] Found via proximity diff=' + bestDiff);
        return best;
    };

    const container = findContainer();

    // ── Step 2: Determine overlay position ───────────────────────────────
    // Use the live bounding rect when we have a container.
    // Fall back to the coords passed from the Python detector.
    let placementX, placementY;
    if (container) {
        const r = container.getBoundingClientRect();
        placementX = Math.round(r.left + window.scrollX);
        placementY = Math.round(r.top  + window.scrollY);
        console.log('[INJECT] Container: ' + container.tagName + '#' + container.id
                    + ' at (' + placementX + ',' + placementY + ')');

        // Hide the real ad using opacity:0 — keeps the slot alive so GPT won't
        // detect a missing element and fire a refresh cycle that overwrites us.
        container.style.setProperty('opacity',        '0',      'important');
        container.style.setProperty('visibility',     'hidden', 'important');
        container.style.setProperty('pointer-events', 'none',   'important');

        // Silence any iframes / ins elements inside the slot too
        container.querySelectorAll('iframe, ins, script').forEach(el => {
            el.style.setProperty('opacity',    '0',      'important');
            el.style.setProperty('visibility', 'hidden', 'important');
        });
    } else {
        // No DOM element found — place directly at the detected coordinates
        placementX = x;
        placementY = y;
        console.log('[INJECT] No container — overlaying at raw coords (' + x + ',' + y + ')');
    }

    // ── Step 3: Remove stale overlay at same position (de-duplicate) ─────
    document.querySelectorAll('[data-injected="1"]').forEach(existing => {
        const ex = parseFloat(existing.style.left || '0');
        const ey = parseFloat(existing.style.top  || '0');
        if (Math.abs(ex - placementX) < 60 && Math.abs(ey - placementY) < 60) {
            existing.remove();
        }
    });

    // ── Step 4: Build overlay div on document.body ───────────────────────
    // Appending to body puts the overlay completely outside any ad-network
    // DOM subtree — Google's GPT refresh cycle cannot touch it.
    const overlay = document.createElement('div');
    overlay.setAttribute('data-injected', '1');
    overlay.style.cssText = (
        'position:absolute!important;' +
        'left:'   + placementX + 'px!important;' +
        'top:'    + placementY + 'px!important;' +
        'width:'  + w          + 'px!important;' +
        'height:' + h          + 'px!important;' +
        'z-index:2147483647!important;' +
        'pointer-events:none!important;' +
        'overflow:hidden!important;' +
        'margin:0!important;padding:0!important;border:none!important;' +
        'transform:none!important;clip-path:none!important;' +
        'background:transparent!important;'
    );

    // ── Step 5: Creative image ────────────────────────────────────────────
    const img = document.createElement('img');
    img.src = base64;
    img.style.cssText = (
        'display:block!important;' +
        'width:'  + w + 'px!important;' +
        'height:' + h + 'px!important;' +
        'margin:0!important;padding:0!important;border:none!important;' +
        'object-fit:fill!important;'
    );
    overlay.appendChild(img);

    // ── Step 6: "Ad" badge ────────────────────────────────────────────────
    const badge = document.createElement('div');
    badge.textContent = 'Ad';
    badge.style.cssText = (
        'position:absolute!important;top:2px!important;right:2px!important;' +
        'background:rgba(255,255,255,0.92)!important;' +
        'border:1px solid #ccc!important;border-radius:2px!important;' +
        'padding:1px 3px!important;font:bold 8px/12px sans-serif!important;' +
        'color:#555!important;pointer-events:none!important;z-index:1!important;'
    );
    overlay.appendChild(badge);

    // Append to body — completely outside any ad-network subtree
    document.body.appendChild(overlay);

    console.log('[INJECT] Overlay placed at (' + placementX + ',' + placementY + ') ' + w + 'x' + h);
    return true;
}
"""


_PASS1_PLACEMENT_JS_OLD = """
([x, y, selector, c_w, c_h, slot_w, slot_h, base64]) => {
    // Always inject at the creative's ORIGINAL dimensions — never scale/compress
    const w = c_w;
    const h = c_h;

    // ── Step 1: Find the ad container element ─────────────────────────────
    const findContainer = () => {
        // --- Pass A: CSS selector + proximity ---
        const cleanSel = (selector || '').replace(/\\s*\\([^)]*\\)\\s*$/, '').trim();
        if (cleanSel) {
            try {
                let best = null, bestDiff = 999;
                document.querySelectorAll(cleanSel).forEach(el => {
                    const r = el.getBoundingClientRect();
                    const diff = Math.abs(r.left + window.scrollX - x) +
                                 Math.abs(r.top  + window.scrollY - y);
                    if (diff < bestDiff) { bestDiff = diff; best = el; }
                });
                if (best && bestDiff < 200) {
                    console.log('[INJECT] Container found via selector: ' + cleanSel + ' diff=' + bestDiff);
                    return best;
                }
            } catch(e) { console.log('[INJECT] Selector error: ' + e.message); }
        }
        // --- Pass B: Proximity + loose size match ---
        let best = null, bestDiff = 200;
        document.querySelectorAll('*').forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width < 10 || r.height < 10) return;
            const diff = Math.abs(r.left + window.scrollX - x) +
                         Math.abs(r.top  + window.scrollY - y);
            if (diff < bestDiff &&
                Math.abs(r.width  - slot_w) < 150 &&
                Math.abs(r.height - slot_h) < 150) {
                bestDiff = diff; best = el;
            }
        });
        if (best) {
            const r = best.getBoundingClientRect();
            console.log('[INJECT] Container found via proximity: ' + best.tagName + ' at (' + Math.round(r.left) + ',' + Math.round(r.top) + ') size=' + Math.round(r.width) + 'x' + Math.round(r.height) + ' diff=' + Math.round(bestDiff));
            return best;
        }
        console.log('[INJECT] No container found for slot ' + slot_w + 'x' + slot_h + ' at (' + x + ',' + y + ')');
        return null;
    };

    // ── AdChoices fast-path ───────────────────────────────────────────
    // For adchoices-confirmed slots we know exactly what element to target.
    // Skip the generic proximity search and go straight to the source.
    let container = null;
    const isAdChoices = (selector || '').includes('adchoices-confirmed');

    if (isAdChoices) {
        // Try to match the specific selector from the scan
        const cleanSel = (selector || '').replace(/\\s*\\([^)]*\\)\\s*$/, '').trim();
        if (cleanSel) {
            try {
                // Find the element closest to the scanned coordinates
                let best = null, bestDiff = 300;
                document.querySelectorAll(cleanSel).forEach(el => {
                    const r = el.getBoundingClientRect();
                    const diff = Math.abs(r.left + window.scrollX - x) +
                                 Math.abs(r.top  + window.scrollY - y);
                    if (diff < bestDiff) { bestDiff = diff; best = el; }
                });
                if (best) {
                    console.log('[INJECT] AdChoices fast-path hit: ' + cleanSel + ' diff=' + bestDiff);
                    container = best;
                }
            } catch(e) {}
        }
        // Fallback: any filled ins.adsbygoogle near the coordinates
        if (!container) {
            let best = null, bestDiff = 300;
            document.querySelectorAll(
                'ins.adsbygoogle[data-ad-status="filled"], div[id$="_host"]'
            ).forEach(el => {
                const r = el.getBoundingClientRect();
                const diff = Math.abs(r.left + window.scrollX - x) +
                             Math.abs(r.top  + window.scrollY - y);
                if (diff < bestDiff) { bestDiff = diff; best = el; }
            });
            if (best) {
                console.log('[INJECT] AdChoices fallback hit diff=' + bestDiff);
                container = best;
            }
        }
    }

    if (!container) container = findContainer();
    if (!container) return false;

    // ── Step 2: Block ad network from re-filling the container ────────────
    const guard = new MutationObserver(mutations => {
        mutations.forEach(m => {
            m.addedNodes.forEach(node => {
                if (node.nodeType === 1 &&
                    (node.tagName === 'IFRAME' || node.tagName === 'INS' ||
                     node.tagName === 'SCRIPT' || (node.id && node.id.startsWith('google_ads')))) {
                    node.remove();
                }
            });
        });
    });
    guard.observe(container, { childList: true, subtree: true });

    // ── Step 3: Hide real ad iframes + clear container ────────────────────
    container.querySelectorAll('iframe, ins, script').forEach(el => {
        el.style.setProperty('display',    'none',    'important');
        el.style.setProperty('visibility', 'hidden',  'important');
    });
    while (container.firstChild) {
        container.removeChild(container.firstChild);
    }

    // ── Step 4: Fix parent chain — remove overflow:hidden clipping
    //            and ensure stacking context doesn't trap our z-index ────────
    let parent = container.parentElement;
    for (let i = 0; i < 6; i++) {
        if (!parent || parent === document.body) break;
        const cs = window.getComputedStyle(parent);
        if (cs.overflow === 'hidden' || cs.overflowX === 'hidden' || cs.overflowY === 'hidden') {
            parent.style.setProperty('overflow', 'visible', 'important');
        }
        if (cs.clipPath && cs.clipPath !== 'none') {
            parent.style.setProperty('clip-path', 'none', 'important');
        }
        // Lift z-index of parent so our container isn't buried in a low stacking context
        const pz = parseInt(cs.zIndex, 10);
        if (!isNaN(pz) && pz < 9999) {
            parent.style.setProperty('z-index', '9999', 'important');
        }
        parent = parent.parentElement;
    }

    // ── Step 5: Size the container to the creative's original dimensions ──
    container.style.setProperty('width',      w + 'px',        'important');
    container.style.setProperty('height',     h + 'px',        'important');
    container.style.setProperty('min-width',  w + 'px',        'important');
    container.style.setProperty('min-height', h + 'px',        'important');
    container.style.setProperty('max-width',  'none',          'important');
    container.style.setProperty('max-height', 'none',          'important');
    container.style.setProperty('overflow',   'visible',       'important');
    container.style.setProperty('display',    'block',         'important');
    container.style.setProperty('visibility', 'visible',       'important');
    container.style.setProperty('opacity',    '1',             'important');
    container.style.setProperty('background', 'transparent',   'important');
    container.style.setProperty('z-index',    '2147483647',    'important');
    container.style.setProperty('position',   'relative',      'important');
    container.style.setProperty('transform',  'none',          'important');
    container.style.setProperty('clip-path',  'none',          'important');

    // ── Step 6: Inject our creative image inside the container ────────────
    const img = document.createElement('img');
    img.src = base64;
    img.setAttribute('data-injected', '1');
    img.style.cssText = [
        'display:block!important',
        'width:'      + w + 'px!important',
        'height:'     + h + 'px!important',
        'min-width:'  + w + 'px!important',
        'min-height:' + h + 'px!important',
        'max-width:none!important',
        'max-height:none!important',
        'border:none!important',
        'margin:0!important',
        'padding:0!important',
        'object-fit:fill!important',
        'visibility:visible!important',
        'opacity:1!important',
        'position:relative!important',
        'z-index:2147483647!important',
        'transform:none!important',
        'clip-path:none!important',
        'box-shadow:none!important',
        'outline:none!important',
        'pointer-events:auto!important',
        'float:none!important',
        'clear:both!important'
    ].join(';');

    // ── Step 7: Small "Ad" badge (top-right corner) ───────────────────────
    const badge = document.createElement('div');
    badge.textContent = 'Ad';
    badge.style.cssText = [
        'position:absolute',
        'top:2px',
        'right:2px',
        'background:rgba(255,255,255,0.92)',
        'border:1px solid #ccc',
        'border-radius:2px',
        'padding:1px 3px',
        'font:bold 8px/12px sans-serif',
        'color:#555',
        'pointer-events:none',
        'z-index:1'
    ].join(';');

    container.appendChild(img);
    container.appendChild(badge);

    console.log('[INJECT] Replaced container at (' + x + ',' + y + ') ' + w + 'x' + h);
    return true;
}
"""  # _PASS1_PLACEMENT_JS_OLD — kept for reference, not used


# ---------------------------------------------------------------------------
# Placement functions
# ---------------------------------------------------------------------------

async def apply_natural_placement(page: Page, creative: dict, url: str = "") -> bool:
    """Injects the creative naturally — horizontal banner or vertical sidebar."""
    try:
        c_w     = creative["width"]
        c_h     = creative["height"]
        base64  = creative["base64"]
        is_vert = c_h > c_w

        logger.info(f"[ENGINE] Natural placement for {url}: {creative['name']} ({c_w}x{c_h}) "
              f"{'vertical' if is_vert else 'horizontal'}")

        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(300)

        result = await page.evaluate(_NATURAL_PLACEMENT_JS, [c_w, c_h, base64, is_vert])

        if result:
            logger.info(f"[ENGINE] Natural placement success: {c_w}x{c_h}")
            return True
        else:
            logger.info(f"[ENGINE] Natural placement JS returned falsy for {url}")
            return False

    except Exception as e:
        logger.info(f"[ENGINE ERROR] Natural placement failed: {e}")
        return False


async def apply_pass1_placement(page: Page, slot: dict, creative: dict) -> bool:
    """Injects the creative into a detected ad slot (Pass 1)."""
    try:
        c_w      = creative["width"]
        c_h      = creative["height"]
        base64   = creative["base64"]
        selector = slot.get("selector", "")
        x        = slot.get("x", 0)
        y        = slot.get("y", 0)
        slot_w   = slot.get("width", 0)
        slot_h   = slot.get("height", 0)

        logger.info(f"[ENGINE] Pass 1 placing {creative['name']} ({c_w}x{c_h}) "
              f"into slot '{selector}' at ({x},{y})")

        # ── Scroll so the slot is in the active viewport before injecting ──
        # getBoundingClientRect() can return wrong/0 coords for off-screen
        # elements in some browsers. Scrolling first ensures the element is
        # rendered and its coords are reliable.
        vp_h = (page.viewport_size or {}).get("height", 900)
        pre_scroll = max(0, y + slot_h // 2 - vp_h // 2)
        await page.evaluate(f"window.scrollTo(0, {pre_scroll})")
        await page.wait_for_timeout(400)   # let layout settle

        success = await page.evaluate(
            _PASS1_PLACEMENT_JS,
            [x, y, selector, c_w, c_h, slot_w, slot_h, base64],
        )

        if success:
            # Brief settle — let the overlay render before we verify
            await page.wait_for_timeout(300)

            # Verify: the overlay div must exist on body with a positive width
            injected = await page.evaluate("""() => {
                const overlays = document.querySelectorAll('body > [data-injected="1"]');
                return overlays.length > 0 && overlays[0].offsetWidth > 0;
            }""")
            if not injected:
                logger.warning("[ENGINE] Overlay not found on body — injection failed")
                success = False

        logger.info(f"[ENGINE] Pass 1 placement result: {success}")
        return bool(success)

    except Exception as e:
        logger.info(f"[ENGINE ERROR] Pass 1 placement failed: {e}")
        return False


async def _inject_address_bar(page: Page, url: str) -> None:
    try:
        parsed      = urlparse(url)
        display_url = parsed.netloc + parsed.path + parsed.query + parsed.fragment
        await page.evaluate(_ADDRESS_BAR_JS, display_url)
        await page.wait_for_timeout(ADDRESS_BAR_WAIT_MS)
    except Exception as e:
        logger.info(f"[ADDRESS BAR] Injection failed: {e}")


async def _inject_mobile_address_bar(page: Page, url: str) -> None:
    try:
        parsed      = urlparse(url)
        display_url = parsed.netloc + parsed.path + parsed.query + parsed.fragment
        await page.evaluate(_MOBILE_ADDRESS_BAR_JS, display_url)
        await page.wait_for_timeout(ADDRESS_BAR_WAIT_MS)
    except Exception as e:
        logger.info(f"[ADDRESS BAR MOBILE] Injection failed: {e}")


# ---------------------------------------------------------------------------
# Single URL processor
# ---------------------------------------------------------------------------

async def process_single_url(
    context: BrowserContext,
    url: str,
    creatives: list,
    creatives_lock: asyncio.Lock,
    emit_cb,
    device: str = "desktop",
) -> dict:
    """Processes a single URL: detect real ad slots, inject creative in-slot, save screenshot."""
    page = await context.new_page()

    # Forward browser console.log → Python logger so [INJECT] messages are visible
    page.on("console", lambda msg: logger.info("[JS] %s", msg.text) if msg.type == "log" else None)

    # Start network-level ad CDN interception immediately (before page loads)
    ad_network_hits = _setup_network_ad_intercept(page)

    await page.add_init_script(_STEALTH_INIT_SCRIPT)
    await page.add_init_script(MUTATION_OBSERVER_SCRIPT)

    _parsed_domain  = urlparse(url).netloc          # e.g. "www.tomsguide.com"
    domain          = _parsed_domain.replace(".", "_")
    os.makedirs("screenshots", exist_ok=True)
    _dev_suffix     = "_mobile" if device == "mobile" else ""
    screenshot_path = f"screenshots/{domain}{_dev_suffix}.png"

    # Per-site creative loading — each URL gets its own mapped creative(s)
    # so a creative assigned to site A is never injected into site B.
    async with creatives_lock:
        site_creatives = get_creatives_for_domain(_parsed_domain, device=device)
    logger.info("[INJECT] Site '%s' → %d creative(s) assigned",
                _parsed_domain, len(site_creatives))
    # Use site_creatives as the working pool for this URL only
    creatives = list(site_creatives)

    final_image_path    = ""
    original_final_path = None
    match_score         = 0.0
    placement_zone      = None
    placement_rule      = None
    condition_used      = None

    try:
        logger.info(f"\n[SCAN] [PASS 1] {url}")

        await _enable_resource_blocking(page, block_ads=False)
        await stealth_async(page)

        await emit_cb({"type": "site_start",   "payload": {"url": url}})
        await emit_cb({"type": "site_loading", "payload": {"url": url}})

        await _navigate_with_retry(page, url)
        await page.wait_for_timeout(INITIAL_PAGE_WAIT_MS)

        # ----------------------------------------------------------------
        # Security page check — EARLY, before wasting time on detection
        # ----------------------------------------------------------------
        if await _is_security_verification_page(page):
            logger.warning(f"[WARN] Access/security block detected for {url}; skipping.")
            await emit_cb({
                "type": "site_failed",
                "payload": {
                    "url": url,
                    "pass_num": 1,
                    "error": "Access denied / security verification page detected",
                },
            })
            return {
                "url": url, "domain": domain, "status": "blocked",
                "condition_used": None, "image_used": None,
                "placement_zone": None, "match_score": 0.0,
                "screenshot_path": "", "url_consumed": False,
                "pass1_injection_failed": False,
                "notes": "Access denied / security verification page detected",
            }

        await close_popups(page)

        # ── Step 1: Accept GDPR / cookie consent banners ─────────────────
        # MUST happen before ad render wait — most ad networks refuse to
        # serve without consent.  accept_consent clicks known CMP buttons.
        await accept_consent(page)
        await page.wait_for_timeout(1500)   # let consent JS propagate

        # ── Step 2: Wait for GPT/DFP iframes to fully render ─────────────
        # Increased to 8 s — after consent, GPT fires ad requests which
        # may take a few seconds to respond with creatives.
        await _wait_for_ads_to_render(page, timeout_ms=8000)

        # Log which ad networks fired — useful for debugging missed slots
        if ad_network_hits:
            active_nets = sorted({h["network"] for h in ad_network_hits})
            logger.info("[NET] %d ad CDN request(s) detected: %s", len(ad_network_hits), active_nets)
        else:
            logger.info("[NET] No known ad CDN requests detected — site may use non-standard networks")

        # Quick above-fold ad scan BEFORE scrolling
        quick_detect   = await detect_ad_slots(page)
        ad_slots_quick = quick_detect.get("slots", [])

        if not ad_slots_quick:
            await emit_cb({"type": "site_scrolling", "payload": {}})
            await _scroll_page(page)

        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(INITIAL_PAGE_WAIT_MS)
        await remove_overlays(page)

        # ── Step 3: Full-page slot detection ─────────────────────────────
        matches_count  = 0
        matched_name   = None
        matched_size   = None
        injection_type = None
        ad_slots       = []

        await emit_cb({"type": "site_detecting", "payload": {}})

        try:
            if ad_slots_quick:
                ad_slots = ad_slots_quick
                logger.info(f"[INFO] Quick scan: {len(ad_slots)} above-fold slots — running scroll-detect")
                extra = await _scroll_and_collect_slots(page)
                for s in extra:
                    duplicate = any(
                        abs(s["x"] - e["x"]) < 10 and abs(s["y"] - e["y"]) < 10
                        for e in ad_slots
                    )
                    if not duplicate:
                        ad_slots.append(s)
                logger.info(f"[INFO] Total after scroll-detect: {len(ad_slots)} slots")
            else:
                ad_slots = await _scroll_and_collect_slots(page)
        except Exception as detect_err:
            logger.warning(f"[WARN] Ad detection failed: {detect_err}")

        # ── Step 4: Extra render wait BEFORE original screenshot ──────────
        # Real ads need time to paint after detection.  We wait here so the
        # "before" screenshot shows fully loaded real ads — not empty slots.
        if ad_slots:
            logger.info("[INJECT] %d slot(s) found — waiting 3s for ads to fully render…", len(ad_slots))
            await page.wait_for_timeout(3000)
        else:
            await page.wait_for_timeout(1000)

        # ── Step 5: Original screenshot (real ads visible) ────────────────
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(400)
        original_path = f"screenshots/{domain}_original.png"
        original_final_path = await _take_screenshot(page, original_path)
        logger.info("[ORIGINAL] Screenshot saved with real ads: %s", original_path)

        # ── Step 6: Vision detection ──────────────────────────────────────
        # VISION DETECTION — merge Claude AI slots with DOM slots
        # If ANTHROPIC_API_KEY is set, Claude looks at the screenshot and
        # finds ads that DOM scanning may have missed (no standard class names).
        if original_final_path:
            try:
                vision_slots = await detect_ads_with_vision(original_final_path)
                added = 0
                for vs in vision_slots:
                    duplicate = any(
                        abs(vs["x"] - s["x"]) < 15 and abs(vs["y"] - s["y"]) < 15
                        for s in ad_slots
                    )
                    if not duplicate:
                        ad_slots.append(vs)
                        added += 1
                if added:
                    logger.info("[VISION] Added %d new slot(s) not found by DOM scan", added)
            except Exception as ve:
                logger.warning("[VISION] Merge failed: %s", ve)

        # ── Step 7: Slot injection — replace real ad slots with client creative ──
        injected_slots    = []
        all_matched_names = []

        async with creatives_lock:
            VIEWPORT_W = 390 if device == "mobile" else 1440

            def _is_good_slot(s):
                sx  = s.get("x", 0)
                sw  = s.get("width", 0)
                sh  = s.get("height", 0)
                sy  = s.get("y", 0)
                if sx + sw <= 0 or sx >= VIEWPORT_W:   # entirely off-screen
                    return False
                if sw < 10 or sh < 10:                 # zero-size
                    return False
                if sy < 0:                             # above document top
                    return False
                return True

            good_slots = [s for s in ad_slots if _is_good_slot(s)]
            logger.info("[INJECT] %d good slot(s) after filter (from %d total)",
                        len(good_slots), len(ad_slots))

            # Determine if the first creative is vertical (sidebar-shaped)
            _first_c = creatives[0] if creatives else None
            _creative_is_vertical = bool(
                _first_c and _first_c.get("height", 0) > _first_c.get("width", 0)
            )

            def _slot_priority(s):
                sel        = s.get("selector", "").lower()
                sx         = s.get("x", 0)
                sy         = s.get("y", 0)
                sw         = s.get("width", 0)
                sh         = s.get("height", 0)
                confidence = s.get("confidence", 0.3)

                # Tier 0 — adchoices-confirmed (real rendered Google ad)
                # Tier 1 — gpt-api / gpt-iframe
                # Tier 2 — everything else
                if "adchoices-confirmed" in sel:
                    tier = 0
                elif "gpt-api-size" in sel or "gpt-iframe" in sel:
                    tier = 1
                else:
                    tier = 2

                # Confidence tier: 0 = high (≥0.7), 1 = medium (≥0.5), 2 = low (<0.5)
                # Inserted between selector-tier and shape so a high-confidence slot
                # always beats a low-confidence one at the same selector tier.
                if confidence >= 0.7:
                    conf_tier = 0
                elif confidence >= 0.5:
                    conf_tier = 1
                else:
                    conf_tier = 2

                # Slot shape match bonus: vertical creative → prefer sidebar slots
                # (right side, taller than wide), horizontal creative → prefer banners
                slot_is_sidebar = sh > sw and sx > VIEWPORT_W * 0.5
                slot_is_banner  = sw > sh

                if _creative_is_vertical:
                    # Sidebar slots match vertical creatives — reward them
                    shape_penalty = 0 if slot_is_sidebar else 1
                else:
                    # Banner/rectangle creative — prefer central & horizontal
                    shape_penalty = 0 if slot_is_banner else 1

                # Above-fold preference (y bucketed to 200px bands)
                above_fold = sy // 200

                # For sidebars: distance from RIGHT edge (not centre)
                # For banners:  distance from horizontal centre
                if slot_is_sidebar:
                    pos_dist = abs(sx + sw - VIEWPORT_W)   # how far from right edge
                else:
                    pos_dist = abs(sx + sw // 2 - VIEWPORT_W // 2)

                area = sw * sh

                return (tier, conf_tier, shape_penalty, above_fold, pos_dist, -area)

            good_slots.sort(key=_slot_priority)

            # ── Non-ad element blocklist ─────────────────────────────────────
            # Reject slots whose selector suggests a non-ad container:
            # newsletter boxes, email signups, cookie banners, social share, etc.
            _BLOCKED_KEYWORDS = [
                "newsletter", "subscribe", "email", "signup", "sign-up",
                "modal", "cookie", "consent", "notification", "promo-banner",
                "social", "share", "comment", "footer", "header", "nav",
                "menu", "search", "login", "register", "form",
            ]
            def _is_non_ad(slot):
                sel = slot.get("selector", "").lower()
                return any(kw in sel for kw in _BLOCKED_KEYWORDS)

            filtered_non_ad = [s for s in good_slots if not _is_non_ad(s)]
            if filtered_non_ad:
                good_slots = filtered_non_ad
                logger.info("[INJECT] Blocked %d non-ad element(s)",
                            len(good_slots) - len(filtered_non_ad))

            # ── Device-aware IAB size filter ──────────────────────────────────
            # Mobile viewport → only mobile-compatible IAB slot sizes.
            # Desktop viewport → reject mobile-only slots (too small).
            _MOBILE_IAB = [(320, 50), (320, 100), (300, 250), (300, 600), (336, 280)]
            _DESKTOP_ONLY_MIN_W = 468   # smallest desktop-only IAB width

            if device == "mobile":
                _mobile_slots = [
                    s for s in good_slots
                    if any(
                        abs(s.get("width", 0) - iw) <= 35
                        and abs(s.get("height", 0) - ih) <= 35
                        for iw, ih in _MOBILE_IAB
                    )
                ]
                if _mobile_slots:
                    good_slots = _mobile_slots
                    logger.info("[INJECT] Mobile device — restricted to %d mobile-IAB slot(s)",
                                len(good_slots))
            else:
                # Desktop: skip slots that are narrower than smallest desktop IAB
                _desktop_slots = [
                    s for s in good_slots
                    if s.get("width", 0) >= _DESKTOP_ONLY_MIN_W
                    or (s.get("width", 0) >= 280 and s.get("height", 0) >= 200)
                ]
                if _desktop_slots:
                    good_slots = _desktop_slots
                    logger.info("[INJECT] Desktop device — restricted to %d desktop slot(s)",
                                len(good_slots))

            # ── Natural placement filter ─────────────────────────────────────
            # Only inject into slots where a real ad is actively rendering
            # (confidence ≥ 65).  Raised from 50 → 65 to prevent false positives
            # like newsletter widgets, promo boxes, or low-confidence positional guesses.
            _NATURAL_CONFIDENCE = 65
            _natural = [s for s in good_slots if s.get("confidence", 0) >= _NATURAL_CONFIDENCE]
            if _natural:
                good_slots = _natural
                logger.info(
                    "[INJECT] %d natural slot(s) with confidence ≥ %d%%",
                    len(good_slots), _NATURAL_CONFIDENCE,
                )
            else:
                logger.warning(
                    "[INJECT] No high-confidence slots — using best available "
                    "(%d slot(s), confidence may be low)",
                    len(good_slots),
                )

            # ── Build candidate list ─────────────────────────────────────────
            # Inject into the single best slot only (natural placement policy).
            MAX_INJECT_SLOTS = 1   # single best-match injection per page (natural placement)
            candidates: list[tuple] = []
            _base_creative = creatives[0] if creatives else None

            for slot in good_slots:
                if len(candidates) >= MAX_INJECT_SLOTS:
                    break
                if not creatives and not _base_creative:
                    break

                # Try exact/close size match first
                matched = find_best_match(slot, creatives, tolerance=PASS1_TOLERANCE)

                # Fallback: resize the base creative to fit the slot exactly.
                # Using resize_creative_for_slot (contain-fit with padding) means
                # the creative is always fully visible without cropping — much
                # better than a wrongly-sized 728×90 crammed into a 300×250 slot.
                if not matched and _base_creative:
                    slot_w_f = slot.get("width",  _base_creative["width"])
                    slot_h_f = slot.get("height", _base_creative["height"])
                    resized  = resize_creative_for_slot(_base_creative, slot_w_f, slot_h_f)
                    if resized:
                        matched = resized
                        logger.info(
                            "[INJECT] Auto-resized '%s' %dx%d → %dx%d for slot",
                            _base_creative["name"],
                            _base_creative["width"], _base_creative["height"],
                            slot_w_f, slot_h_f,
                        )
                    else:
                        # resize failed (PIL not available, etc.) — fall back to raw clone
                        matched = _base_creative.copy()
                        matched['match_score'] = 0.5
                        logger.info(
                            "[INJECT] Resize failed — cloning '%s' at %dx%d for slot",
                            _base_creative["name"],
                            _base_creative["width"], _base_creative["height"],
                        )

                if not matched:
                    continue

                # Remove from pool only if it's a unique creative (not a clone)
                original_c = next((c for c in creatives if c["name"] == matched["name"]), None)
                if original_c and original_c is not _base_creative:
                    creatives.remove(original_c)
                # When _base_creative is cloned we leave it in the pool

                candidates.append((slot, matched))
                all_matched_names.append(matched["name"])

        logger.info("[INJECT] %d candidate slot(s) queued (will retry on failure)", len(candidates))

        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)
        first_injected_slot = None

        # ── Inject into ALL candidate slots ─────────────────────────────────
        # We no longer stop after the first success — we fill every valid slot.
        # The screenshot will scroll to the LARGEST injected slot for the best view.
        best_slot_for_screenshot = None   # largest area among all successes
        best_area = 0

        for attempt_num, (slot, creative) in enumerate(candidates, start=1):
            success = await apply_pass1_placement(page, slot, creative)
            if success:
                matches_count += 1
                sw = slot.get("width",  creative["width"])
                sh = slot.get("height", creative["height"])
                matched_name   = matched_name or creative["name"]
                matched_size   = matched_size or f"{sw}x{sh}"
                injection_type = "slot-injection"
                condition_used = 1
                if first_injected_slot is None:
                    first_injected_slot = slot
                # Track the largest successful slot for screenshot centering
                area = sw * sh
                if area > best_area:
                    best_area = area
                    best_slot_for_screenshot = slot

                await emit_cb({
                    "type": "match_success",
                    "payload": {
                        "creative_name": creative["name"],
                        "url": url,
                        "dimensions": f"{sw}x{sh}",
                    },
                })
                logger.info(
                    "╔══════════════════════════════════════════════════╗\n"
                    "║  ✅  SLOT INJECTION SUCCESS (%d/%d)               ║\n"
                    "║  Creative : %-36s║\n"
                    "║  Slot     : %-4dx%-4d  pos x=%-4d y=%-4d      ║\n"
                    "║  Site     : %-36s║\n"
                    "╚══════════════════════════════════════════════════╝",
                    matches_count, len(candidates),
                    creative["name"][:36], sw, sh,
                    slot.get("x", 0), slot.get("y", 0),
                    domain[:36],
                )
                # Continue to next slot — don't break
            else:
                logger.warning(
                    "[RETRY] Slot %d/%d at (%d,%d) failed — skipping",
                    attempt_num, len(candidates), slot.get("x", 0), slot.get("y", 0)
                )

        # Use best (largest) slot for screenshot framing
        if best_slot_for_screenshot is not None:
            first_injected_slot = best_slot_for_screenshot

        # For backwards compat: keep injected_slots populated for visibility check
        if first_injected_slot is not None:
            injected_slots = [(first_injected_slot, None)]

        if matches_count == 0:
            logger.info("[INFO] No slot injection succeeded on %s", url)
            await emit_cb({"type": "no_match_on_site", "payload": {"url": url, "pass_num": 1}})
            return {
                "url": url, "domain": domain, "status": "skipped",
                "condition_used": None, "image_used": None,
                "placement_zone": None, "match_score": 0.0,
                "screenshot_path": "",
                "url_consumed": False,
                "pass1_injection_failed": len(injected_slots) > 0,
                "notes": "No ad slot found or injection failed",
            }

        # ----------------------------------------------------------------
        # ----------------------------------------------------------------
        # Verify injection succeeded — trust apply_pass1_placement's own
        # verify rather than re-polling (page scripts can clear body between
        # the two checks, causing false failures and 0/N screenshots).
        # Single sanity check; if overlays were cleared by the page we still
        # proceed — the screenshot may still capture the injected creative.
        # ----------------------------------------------------------------
        if matches_count > 0:
            live_count = await page.evaluate("""
                () => document.querySelectorAll('body > [data-injected="1"]').length
            """)
            if live_count > 0:
                logger.info("[VERIFY] ✅ %d overlay(s) live on body — proceeding to screenshot",
                            live_count)
            else:
                # Overlays were present at inject-time (verified by apply_pass1_placement)
                # but were since cleared by a page script.  Re-inject the best slot
                # one more time before giving up.
                logger.warning(
                    "[VERIFY] Overlays cleared by page script on %s — re-injecting best slot", url
                )
                if best_slot_for_screenshot is not None:
                    best_creative_name = all_matched_names[0] if all_matched_names else None
                    # Rebuild the creative from the candidate list for re-injection
                    best_pair = next(
                        ((sl, cr) for sl, cr in candidates
                         if sl is best_slot_for_screenshot),
                        None,
                    )
                    if best_pair:
                        reinjected = await apply_pass1_placement(page, best_pair[0], best_pair[1])
                        if reinjected:
                            logger.info("[VERIFY] ✅ Re-injection succeeded — proceeding to screenshot")
                        else:
                            logger.warning("[VERIFY] Re-injection failed — screenshot may show missing creative")
            logger.info("[VERIFY] Proceeding to screenshot for %d injected slot(s)", matches_count)

        # ----------------------------------------------------------------
        # Screenshot + address bar
        # ----------------------------------------------------------------
        # Wait for injection to fully paint before scrolling/screenshotting
        await page.wait_for_timeout(POST_MASK_WAIT_MS)

        if first_injected_slot is not None:
            slot_x = first_injected_slot.get("x", 0)
            slot_y = first_injected_slot.get("y", 0)
            slot_w = first_injected_slot.get("width", 300)
            slot_h = first_injected_slot.get("height", 250)

            # Pre-scroll to the slot so the address bar renders in the right context
            vp_h_now = (page.viewport_size or {}).get("height", 900)
            pre_scroll = max(0, slot_y + slot_h // 2 - vp_h_now // 2)
            await page.evaluate(f"window.scrollTo(0, {pre_scroll})")
            await page.wait_for_timeout(600)   # let ads settle after scroll

        # Inject address bar overlay
        if device == "mobile":
            await _inject_mobile_address_bar(page, url)
        else:
            await _inject_address_bar(page, url)
        await page.wait_for_timeout(300)

        if first_injected_slot is not None:
            final_image_path = await _take_injection_screenshot(
                page, screenshot_path, slot_x, slot_y, slot_w, slot_h, padding=150
            )
        else:
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(300)
            final_image_path = await _take_screenshot(page, screenshot_path)

        if final_image_path and os.path.isfile(final_image_path):
            logger.info(
                "\n"
                "╔══════════════════════════════════════════════════╗\n"
                "║  📸  SCREENSHOT DONE                             ║\n"
                "║  File : %-40s║\n"
                "║  URL  : %-40s║\n"
                "╚══════════════════════════════════════════════════╝",
                os.path.basename(final_image_path)[:40],
                url[:40],
            )

        if not final_image_path or not os.path.isfile(final_image_path):
            logger.info(f"[SCAN SKIP] {url}: screenshot not created.")
            await emit_cb({
                "type": "site_failed",
                "payload": {"url": url, "pass_num": 1,
                            "error": "Screenshot file was not created"},
            })
            return {
                "url": url, "domain": domain, "status": "failed",
                "condition_used": condition_used, "image_used": matched_name,
                "placement_zone": placement_zone, "match_score": match_score,
                "screenshot_path": "",
                "url_consumed": False,
                "pass1_injection_failed": False,
                "notes": "Screenshot file was not created",
            }

        # ── Before/After composite ────────────────────────────────────────
        comparison_path = None
        if (
            final_image_path and original_final_path
            and os.path.isfile(final_image_path)
            and os.path.isfile(original_final_path)
        ):
            try:
                from PIL import Image as _PILC, ImageDraw as _DrawC, ImageFont as _FontC
                import io as _ioC

                img_orig = _PILC.open(original_final_path).convert("RGB")
                img_inj  = _PILC.open(final_image_path).convert("RGB")

                # Normalise both images to the same height (cap at 900px)
                target_h = min(img_orig.height, img_inj.height, 900)
                def _resize_to_h(img, h):
                    ratio = h / img.height
                    return img.resize((int(img.width * ratio), h), _PILC.LANCZOS)

                img_orig_r = _resize_to_h(img_orig, target_h)
                img_inj_r  = _resize_to_h(img_inj,  target_h)

                label_h = 44
                gap     = 8
                canvas_w = img_orig_r.width + gap + img_inj_r.width
                canvas   = _PILC.new("RGB", (canvas_w, target_h + label_h), (22, 22, 32))

                # Label bars
                draw = _DrawC.Draw(canvas)
                draw.rectangle([(0, 0), (img_orig_r.width, label_h - 1)], fill=(45, 45, 60))
                draw.rectangle([(img_orig_r.width + gap, 0), (canvas_w, label_h - 1)], fill=(20, 65, 35))

                try:
                    font = _FontC.truetype("arial.ttf", 15)
                except Exception:
                    font = _FontC.load_default()

                draw.text((12, 13), "BEFORE — real ads", fill=(180, 180, 200), font=font)
                draw.text((img_orig_r.width + gap + 12, 13), "AFTER — client creative", fill=(130, 240, 130), font=font)

                # Paste images
                canvas.paste(img_orig_r, (0, label_h))
                canvas.paste(img_inj_r,  (img_orig_r.width + gap, label_h))

                comparison_path = f"screenshots/{domain}_comparison.png"
                canvas.save(comparison_path)
                logger.info("[COMPOSITE] Before/after saved: %s", comparison_path)
            except Exception as _ce:
                logger.warning("[COMPOSITE] Failed to create before/after: %s", _ce)

        # Summary for multi-slot: list all injected creatives
        all_names_str = ", ".join(all_matched_names) if all_matched_names else matched_name
        notes_str = (
            f"{matches_count} slot(s) replaced | "
            f"creatives: {all_names_str} | "
            f"type: {injection_type}"
        )

        await _save_to_db(
            url=url,
            final_image_path=final_image_path,
            ad_slots=ad_slots,
            matches_count=matches_count,
            matched_name=all_names_str,
            matched_size=matched_size,
            injection_type=injection_type,
            viewport=page.viewport_size,
            original_image_path=original_final_path,
            match_score=match_score,
        )

        return {
            "url": url, "domain": domain, "status": "success",
            "condition_used": condition_used, "image_used": all_names_str,
            "placement_zone": placement_zone, "match_score": round(match_score, 2),
            "screenshot_path": final_image_path,
            "original_screenshot_path": original_final_path,
            "comparison_screenshot_path": comparison_path,
            "slots_replaced": matches_count,
            "url_consumed": condition_used == 1,
            "pass1_injection_failed": False,
            "notes": notes_str,
        }

    except Exception as e:
        logger.info(f"[SCAN FAILED] {url}: {e}")
        traceback.print_exc()
        await emit_cb({
            "type": "site_failed",
            "payload": {"url": url, "pass_num": 1, "error": str(e)},
        })
        return {
            "url": url, "domain": domain, "status": "failed",
            "condition_used": None, "image_used": None,
            "placement_zone": None, "match_score": 0.0,
            "screenshot_path": "",
            "url_consumed": False,
            "pass1_injection_failed": False,
            "notes": str(e),
        }
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def open_website(urls: list[str] | None = None, emit_cb=None, device: str = "desktop") -> dict:
    """Orchestrator — smart multi-slot ad replacement pipeline.

    device — "desktop" (default) | "mobile"
      desktop : 1440×900 viewport, standard Chrome UA
      mobile  : 390×844 viewport, iPhone 14 Safari UA, scale=2, touch enabled
    """
    if emit_cb is None:
        async def dummy_cb(event): return None
        emit_cb = dummy_cb

    if not urls:
        urls = [
            "https://sports.ndtv.com/",
            "https://thesportstak.com/",
            "https://www.espncricinfo.com/",
            "https://www.cricbuzz.com/",
            "https://www.mykhel.com/",
        ]

    pw = browser = context = None
    results: list[dict] = []

    # ── Auto-detect device from creative dimensions ────────────────────────
    # If every uploaded creative is mobile-sized (width ≤ 414 px) and the
    # caller did not explicitly request "mobile", switch automatically so the
    # page loads at the right viewport and the injection looks natural.
    if device == "desktop":
        _peek = get_local_creatives()          # load ALL creatives (no device filter)
        if _peek:
            _max_w = max(c["width"] for c in _peek)
            if _max_w <= 414:
                device = "mobile"
                logger.info(
                    "[ENGINE] Creative max-width=%dpx ≤ 414 — auto-switching to mobile viewport",
                    _max_w,
                )

    # ── Device-specific browser config ────────────────────────────────────
    is_mobile = device == "mobile"
    if is_mobile:
        _viewport    = {"width": 390, "height": 844}
        _scale       = 2
        _ua          = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        )
        _window_size = "--window-size=390,844"
    else:
        _viewport    = {"width": 1440, "height": 900}
        _scale       = 1
        _ua          = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
        _window_size = "--window-size=1440,900"

    try:
        pw      = await async_playwright().start()
        from core.config import get_settings as _get_settings
        _cfg = _get_settings()

        # Use a persistent user data dir so cookies build up across runs
        # (makes the browser look more like a real returning user to bot detectors).
        # On Linux/cloud (Render) use /tmp so there are no write-permission issues.
        import pathlib
        _dir_suffix   = "mobile" if is_mobile else "desktop"
        _bdata_name   = f"browser_data_{_dir_suffix}"
        if sys.platform == "win32":
            user_data_dir = str(pathlib.Path(_bdata_name).resolve())
        else:
            # /tmp is always writable; path survives within a dyno session
            user_data_dir = f"/tmp/{_bdata_name}"
        pathlib.Path(user_data_dir).mkdir(parents=True, exist_ok=True)

        context = await pw.chromium.launch_persistent_context(
            user_data_dir,
            headless=_cfg.headless,
            viewport=_viewport,
            device_scale_factor=_scale,
            is_mobile=is_mobile,
            has_touch=is_mobile,
            user_agent=_ua,
            locale="en-US",
            timezone_id="America/New_York",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                _window_size,
                "--no-first-run",
                "--no-service-autorun",
                "--password-store=basic",
                "--use-mock-keychain",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT":             "1",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest":  "document",
                "Sec-Fetch-Mode":  "navigate",
                "Sec-Fetch-Site":  "none",
                "Sec-Fetch-User":  "?1",
            },
            java_script_enabled=True,
        )

        master_creatives = get_local_creatives(device=device)
        creatives_lock   = asyncio.Lock()
        max_concurrency  = DEFAULT_MAX_CONCURRENCY

        await emit_cb({
            "type": "started",
            "payload": {
                "creatives": [
                    {"name": c["name"], "width": c["width"], "height": c["height"]}
                    for c in master_creatives
                ]
            },
        })
        await emit_cb({"type": "pass_start", "payload": {"pass_num": 1}})

        async def run_batch(batch_urls: list[str]) -> list[dict]:
            tasks = [
                # All URLs share the same pool + lock so each creative is
                # consumed by exactly one website and never reused.
                process_single_url(
                    context, u,
                    master_creatives,   # shared pool
                    creatives_lock,     # shared lock
                    emit_cb,
                    device,             # "desktop" | "mobile"
                )
                for u in batch_urls
            ]
            return list(await asyncio.gather(*tasks))

        # Process all URLs in batches
        idx = 0
        while idx < len(urls):
            batch  = urls[idx:idx + max_concurrency]
            idx   += len(batch)
            results.extend(await run_batch(batch))

        # Notify frontend about creatives with no matching slot
        for c in list(master_creatives):
            await emit_cb({
                "type": "unplaced_creative",
                "payload": {"creative_name": c["name"], "reason": "no_matching_slot"},
            })

        succeeded = sum(
            1 for r in results
            if r.get("screenshot_path") and os.path.isfile(r["screenshot_path"])
        )
        logger.info("[ENGINE] Finished. %d/%d URLs succeeded.", succeeded, len(urls))
        await emit_cb({
            "type": "finished",
            "payload": {
                "results":   results,
                "succeeded": succeeded,
                "total":     len(urls),
            },
        })
        return {"results": results, "succeeded": succeeded}

    except Exception as e:
        logger.exception("[ENGINE] Fatal error: %s", e)
        await emit_cb({"type": "error", "payload": {"message": str(e)}})
        return {"results": results, "succeeded": 0}

    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass
        if pw:
            try:
                await pw.stop()
            except Exception:
                pass
