import asyncio
import json
from playwright.async_api import Page


# ==========================================
# CONFIG
# ==========================================

CONFIG = {
    "selectors": [
        # Google / DFP
        'ins.adsbygoogle',
        '[id^="google_ads_iframe"]',
        '[id^="div-gpt-ad"]',
        '[id*="gpt-ad"]',
        '[id*="dfp-ad"]',
        '[data-ad-unit-path]',
        '[data-google-query-id]',
        # Common ad wrappers
        '[class*="ad-unit"]',
        '[id*="ad-unit"]',
        '[class*="adUnit"]',
        '[id*="adUnit"]',
        '[class*="adBox"]',
        '[class*="ad-box"]',
        '[class*="AdBox"]',
        '[class*="adBlock"]',
        '[class*="ad-block"]',
        '[class*="advertisement"]',
        '[class*="Advertisement"]',
        '[class*="advert"]',
        '[class*="Advert"]',
        '[class*="sponsored-post"]',
        '[class*="sponsored"]',
        '.ad-container',
        '.ad-slot',
        '.ad-wrap',
        '.adswrapper',
        # Third-party
        '.trc_rbox_container',
        '.outbrain',
        'iframe[src*="doubleclick.net"]',
        'iframe[src*="googlesyndication.com"]',
        'iframe[id^="ads-"]',
        # Dawn.com / News site patterns
        '[id*="dawn-ad"]',
        '[class*="dawn-ad"]',
        '.story-advertisement',
        '.article-advertisement',
        '.sidebar-ad',
        '.sidebar-advertisement',
        # Sidebar / right-rail patterns (common across news sites)
        '[class*="sidebar"]',
        '[id*="sidebar"]',
        '[class*="right-rail"]',
        '[id*="right-rail"]',
        '[class*="rail-ad"]',
        '[id*="rail-ad"]',
        '[class*="sticky-ad"]',
        '[id*="sticky-ad"]',
        '[class*="ad-sticky"]',
        '[class*="ad-sidebar"]',
        '[class*="adSidebar"]',
        '[class*="side-ad"]',
        '[class*="sideAd"]',
        '[class*="widget-ad"]',
        '[class*="adWidget"]',
        # IAB 300x250 / 300x600 / 160x600 placeholder divs
        'div[style*="width:300px"]',
        'div[style*="width: 300px"]',
        'div[style*="width:160px"]',
        'div[style*="width: 160px"]',
        # Major news-site specific ad patterns
        '[class*="ad-placeholder"]',
        '[class*="adPlaceholder"]',
        '[class*="ad-wrapper"]',
        '[class*="adWrapper"]',
        '[class*="ad-region"]',
        '[class*="adRegion"]',
        '[class*="ad-zone"]',
        '[class*="adZone"]',
        '[class*="ad-holder"]',
        '[class*="adHolder"]',
        '[class*="ad-frame"]',
        '[id*="ad-placeholder"]',
        '[id*="ad-holder"]',
        '[id*="ad-wrapper"]',
        '[id*="ad-zone"]',
        # ABC News / Disney / ESPN / premium news ad patterns
        '[data-ad-type]',
        '[data-ad-format]',
        '[data-ad-size]',
        '[data-ad-placement]',
        '[data-slot]',
        '[data-dfp-ad]',
        '[class*="Billboard"]',
        '[class*="MediumRectangle"]',
        '[class*="HalfPage"]',
        '[class*="Leaderboard"]',
        '[class*="SkyScraper"]',
    ],

    "network_keywords": [
        "doubleclick",
        "googlesyndication",
        "taboola",
        "outbrain",
        "ads",
        "adservice"
    ],

    "high_confidence_keywords": [
        "adsbygoogle",
        "div-gpt-ad",
        "doubleclick",
        "googlesyndication",
        "taboola",
        "outbrain"
    ],

    "medium_keywords": [
        "ad-slot",
        "ad-unit",
        "ad-container",
        "sponsored",
        "advertisement"
    ],

    "iab_sizes": [
        # Leaderboards / banners
        (728,  90),   # Leaderboard
        (970,  90),   # Large Leaderboard
        (970, 250),   # Billboard
        (468,  60),   # Half Banner
        # Rectangles
        (300, 250),   # Medium Rectangle (highest fill rate)
        (336, 280),   # Large Rectangle
        (250, 250),   # Square
        (200, 200),   # Small Square
        # Sidebars / skyscrapers
        (300, 600),   # Half Page
        (300,1050),   # Portrait
        (160, 600),   # Wide Skyscraper
        (120, 600),   # Skyscraper
        # Mobile
        (320,  50),   # Mobile Banner
        (320, 100),   # Large Mobile Banner
        # Misc
        (300, 100),   # 3:1 Rectangle
    ]
}


# ==========================================
# MUTATION OBSERVER
# ==========================================

MUTATION_OBSERVER_SCRIPT = """
() => {

    if (window.__adObserverInstalled) {
        return;
    }

    window.__dynamicAds = [];

    const keywords = [
        'adsbygoogle',
        'doubleclick',
        'ad-slot',
        'googlesyndication',
        'sponsored'
    ];

    const observer = new MutationObserver((mutations) => {

        mutations.forEach(mutation => {

            mutation.addedNodes.forEach(node => {

                if (!(node instanceof HTMLElement)) {
                    return;
                }

                const html =
                    (node.outerHTML || '').toLowerCase();

                const matched = keywords.some(
                    keyword => html.includes(keyword)
                );

                if (matched) {

                    const rect =
                        node.getBoundingClientRect();

                    window.__dynamicAds.push({

                        x: Math.round(
                            rect.left + window.scrollX
                        ),

                        y: Math.round(
                            rect.top + window.scrollY
                        ),

                        width: Math.round(rect.width),

                        height: Math.round(rect.height),

                        selector:
                            node.tagName.toLowerCase()
                    });
                }
            });
        });
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    window.__adObserverInstalled = true;
}
"""

# JS for DOM scan — kept separate from f-string to avoid injection issues
DOM_SCAN_SCRIPT = """
(selectors) => {

    const results = [];

    // When an element is 0x0 (e.g. GPT outer div before iframe loads),
    // fall back to its first visible child iframe's dimensions.
    function getRealRect(el) {
        let rect = el.getBoundingClientRect();
        if (rect.width < 10 || rect.height < 10) {
            const iframe = el.querySelector('iframe');
            if (iframe) {
                const fr = iframe.getBoundingClientRect();
                if (fr.width > 10 && fr.height > 10) rect = fr;
            }
        }
        return rect;
    }

    const candidates =
        document.querySelectorAll(selectors.join(', '));

    candidates.forEach(el => {

        const rect  = getRealRect(el);
        const style = window.getComputedStyle(el);

        const visible =
            style.display !== 'none' &&
            style.visibility !== 'hidden' &&
            style.opacity !== '0';

        if (rect.width > 10 && rect.height > 10 && visible) {

            results.push({
                x: Math.round(rect.left + window.scrollX),
                y: Math.round(rect.top  + window.scrollY),
                width:  Math.round(rect.width),
                height: Math.round(rect.height),
                selector:
                    el.tagName.toLowerCase() +
                    (el.id ? '#' + el.id : '') +
                    (
                        el.className &&
                        typeof el.className === 'string'
                        ? '.' + el.className.trim().split(/\\s+/).join('.')
                        : ''
                    )
            });
        }
    });

    // -------------------------
    // GPT ZERO-SIZE FALLBACK
    // Catches div-gpt-ad containers whose own rect is 0x0
    // but whose child iframe has already rendered.
    // -------------------------
    document.querySelectorAll(
        '[id^="div-gpt-ad"], [id*="gpt-ad"], [id*="dfp-ad"]'
    ).forEach(el => {
        const iframe = el.querySelector('iframe');
        if (!iframe) return;
        const fr = iframe.getBoundingClientRect();
        if (fr.width < 10 || fr.height < 10) return;
        const ax = Math.round(fr.left + window.scrollX);
        const ay = Math.round(fr.top  + window.scrollY);
        const exists = results.some(r =>
            Math.abs(r.x - ax) < 10 && Math.abs(r.y - ay) < 10
        );
        if (!exists) {
            results.push({
                x: ax, y: ay,
                width:  Math.round(fr.width),
                height: Math.round(fr.height),
                selector: 'div#' + el.id + ' (gpt-iframe-fallback)'
            });
        }
    });

    // -------------------------
    // GENERIC IFRAME SCAN
    // -------------------------

    document.querySelectorAll('iframe').forEach(el => {

        const rect = el.getBoundingClientRect();
        const src  = el.src || '';

        const looksLikeAd =
            src.includes('doubleclick') ||
            src.includes('googlesyndication') ||
            src.includes('googleads') ||
            src.includes('adserv') ||
            (src.includes('ads') && !src.includes('videads'));

        if (looksLikeAd && rect.width > 50 && rect.height > 50) {

            const ax = Math.round(rect.left + window.scrollX);
            const ay = Math.round(rect.top  + window.scrollY);
            const exists = results.some(r =>
                Math.abs(r.x - ax) < 5 && Math.abs(r.y - ay) < 5
            );

            if (!exists) {
                results.push({
                    x: ax, y: ay,
                    width:  Math.round(rect.width),
                    height: Math.round(rect.height),
                    selector: 'iframe (src-match)'
                });
            }
        }
    });

    // =========================================================
    // ADCHOICES ANCHOR SCAN  — v2
    //
    // Strategy: find CONFIRMED rendered Google ads, then walk
    // the DOM to get the best injection container + exact size.
    //
    // Pass A: ins.adsbygoogle[data-ad-status="filled"]
    //   data-ad-status="filled" means Google has 100% served an ad.
    //   Get the exact rendered size from the child aswift_ iframe.
    //   Record the ins element itself as the injection target.
    //
    // Pass B: iframe[id^="aswift_"] / iframe[id^="google_ads_iframe_"]
    //   Google's actual ad iframes — confirmed rendered.
    //   Walk up to the ins parent (best container for injection).
    //
    // Pass C: div[id*="_host"] containing rendered iframes
    //   Google wraps each iframe in a *_host div — another anchor.
    // =========================================================
    try {
        const _addAC = (el, w, h, ax, ay, label) => {
            if (w < 30 || h < 20) return;
            const dup = results.some(rv =>
                Math.abs(rv.x - ax) < 15 && Math.abs(rv.y - ay) < 15
            );
            if (!dup) {
                results.push({
                    x: ax, y: ay, width: w, height: h,
                    selector: label + ' (adchoices-confirmed)'
                });
            }
        };

        // ── Pass A: ins.adsbygoogle[data-ad-status="filled"] ──────────
        document.querySelectorAll(
            'ins.adsbygoogle[data-ad-status="filled"]'
        ).forEach(ins => {
            // Prefer the aswift_ iframe's rect — it's the true render size
            const iframe = ins.querySelector('iframe[id^="aswift_"]')
                        || ins.querySelector('iframe');
            let w, h, ax, ay;
            if (iframe) {
                const fr = iframe.getBoundingClientRect();
                w  = Math.round(fr.width);
                h  = Math.round(fr.height);
                ax = Math.round(fr.left + window.scrollX);
                ay = Math.round(fr.top  + window.scrollY);
            } else {
                const r = ins.getBoundingClientRect();
                w  = Math.round(r.width);
                h  = Math.round(r.height);
                ax = Math.round(r.left + window.scrollX);
                ay = Math.round(r.top  + window.scrollY);
            }
            const sel = ins.id ? 'ins#' + ins.id : 'ins.adsbygoogle';
            _addAC(ins, w, h, ax, ay, sel);
        });

        // ── Pass B: Google's aswift_ / google_ads_iframe_ iframes ─────
        document.querySelectorAll(
            'iframe[id^="aswift_"], iframe[id^="google_ads_iframe_"]'
        ).forEach(iframe => {
            const r = iframe.getBoundingClientRect();
            if (r.width < 30 || r.height < 20) return;
            const ax = Math.round(r.left + window.scrollX);
            const ay = Math.round(r.top  + window.scrollY);

            // Walk up max 4 levels to find the ins or host div
            let container = iframe.parentElement;
            for (let i = 0; i < 4; i++) {
                if (!container || container === document.body) break;
                const tag = container.tagName.toLowerCase();
                const cid = (container.id || '').toLowerCase();
                if (tag === 'ins' || cid.includes('aswift') ||
                    cid.includes('google_ads') || cid.includes('_host')) break;
                container = container.parentElement;
            }
            const target = container || iframe;
            const sel = target.id
                ? target.tagName.toLowerCase() + '#' + target.id
                : target.tagName.toLowerCase();
            _addAC(target,
                Math.round(r.width), Math.round(r.height),
                ax, ay, sel);
        });

        // ── Pass C: *_host divs wrapping a rendered iframe ────────────
        document.querySelectorAll('div[id$="_host"]').forEach(host => {
            const iframe = host.querySelector('iframe');
            if (!iframe) return;
            const r = iframe.getBoundingClientRect();
            if (r.width < 30 || r.height < 20) return;
            const ax = Math.round(r.left + window.scrollX);
            const ay = Math.round(r.top  + window.scrollY);
            _addAC(host,
                Math.round(r.width), Math.round(r.height),
                ax, ay, 'div#' + host.id);
        });

    } catch(e) {}

    // =========================================================
    // GPT DEFINED-SLOT SCAN  (via googletag API)
    // Works even when the div is 0×0 — ad hasn't loaded yet.
    // googletag.pubads().getSlots() returns ALL configured slots
    // with their intended sizes, regardless of render state.
    // =========================================================
    try {
        if (window.googletag &&
            typeof window.googletag.pubads === 'function') {

            const IAB = [
                // Leaderboards
                [728,90],[970,90],[970,250],[468,60],
                // Rectangles
                [300,250],[336,280],[250,250],[200,200],
                // Sidebars
                [300,600],[300,1050],[160,600],[120,600],
                // Mobile
                [320,50],[320,100],
                // Misc
                [300,100]
            ];

            window.googletag.pubads().getSlots().forEach(slot => {
                try {
                    const elId = slot.getSlotElementId();
                    const el   = document.getElementById(elId);
                    if (!el) return;

                    // Already detected with real size — skip
                    const er = el.getBoundingClientRect();
                    if (er.width > 10 && er.height > 10) return;
                    const iframe = el.querySelector('iframe');
                    if (iframe) {
                        const fr = iframe.getBoundingClientRect();
                        if (fr.width > 10 && fr.height > 10) return;
                    }

                    // Get configured sizes for current viewport
                    const rawSizes = slot.getSizes(
                        window.innerWidth,
                        window.innerHeight
                    );
                    if (!rawSizes || rawSizes.length === 0) return;

                    // Pick best IAB size; fallback to first valid size
                    let bestW = 0, bestH = 0;
                    for (const sz of rawSizes) {
                        if (!sz || sz === 'fluid' ||
                            typeof sz.getWidth !== 'function') continue;
                        const w = sz.getWidth();
                        const h = sz.getHeight();
                        if (w < 50 || h < 20) continue;
                        const isIAB = IAB.some(
                            ([iw,ih]) =>
                                Math.abs(w-iw) <= 8 &&
                                Math.abs(h-ih) <= 8
                        );
                        if (isIAB) { bestW = w; bestH = h; break; }
                        if (!bestW) { bestW = w; bestH = h; }
                    }
                    if (!bestW || !bestH) return;

                    // Position: use parent chain to find first positioned el
                    let posEl = el;
                    let posRect = posEl.getBoundingClientRect();
                    if (posRect.width < 5 && posRect.height < 5) {
                        posEl = el.parentElement || el;
                        posRect = posEl.getBoundingClientRect();
                    }
                    const ax = Math.round(posRect.left + window.scrollX);
                    const ay = Math.round(posRect.top  + window.scrollY);

                    // Skip truly un-positioned slots (top of page, 0,0)
                    if (ay === 0 && ax === 0) return;

                    const dup = results.some(r =>
                        Math.abs(r.x - ax) < 20 &&
                        Math.abs(r.y - ay) < 20
                    );
                    if (!dup) {
                        results.push({
                            x: ax, y: ay,
                            width:  bestW,
                            height: bestH,
                            selector: 'div#' + elId + ' (gpt-api-size)'
                        });
                    }
                } catch(slotErr) { /* individual slot error — skip */ }
            });
        }
    } catch(e) { /* googletag not ready or unavailable — skip */ }

    // =========================================================
    // ADSENSE DATA-ATTRIBUTE SCAN
    // ins.adsbygoogle with explicit data-ad-width / data-ad-height
    // covers responsive AdSense slots that are 0×0 before fill.
    // =========================================================
    document.querySelectorAll('ins.adsbygoogle').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width > 10 && r.height > 10) return; // already captured

        const w = parseInt(
            el.getAttribute('data-ad-width')  ||
            el.getAttribute('data-width')     || '0', 10
        );
        const h = parseInt(
            el.getAttribute('data-ad-height') ||
            el.getAttribute('data-height')    || '0', 10
        );
        if (w < 50 || h < 20) return;

        const pr = el.parentElement
            ? el.parentElement.getBoundingClientRect()
            : r;
        const ax = Math.round((r.width > 1 ? r.left : pr.left) + window.scrollX);
        const ay = Math.round((r.width > 1 ? r.top  : pr.top)  + window.scrollY);
        if (ay === 0 && ax === 0) return;

        const dup = results.some(r2 =>
            Math.abs(r2.x - ax) < 20 && Math.abs(r2.y - ay) < 20
        );
        if (!dup) {
            results.push({
                x: ax, y: ay,
                width: w, height: h,
                selector: 'ins.adsbygoogle (data-attr-size)'
            });
        }
    });

    // =========================================================
    // LEADERBOARD POSITIONAL SCAN
    // Catch 728x90 / 970x90 / 970x250 banners near the top of the page
    // (below nav, typically y=60–250) even without ad-specific class names.
    // =========================================================
    try {
        const IAB_LEADER = [
            [728,90],[970,90],[970,250],[970,66],[468,60],[320,50],[320,100],[300,100]
        ];
        document.querySelectorAll('div, section, aside').forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width < 50 || r.height < 20) return;
            const ay = Math.round(r.top  + window.scrollY);
            const ax = Math.round(r.left + window.scrollX);
            if (ay > 400) return;   // leaderboards are near the top
            if (ay < 30)  return;   // skip elements above the nav
            const matched = IAB_LEADER.some(
                ([iw,ih]) => Math.abs(r.width-iw) <= 30 && Math.abs(r.height-ih) <= 20
            );
            if (!matched) return;
            const dup = results.some(rv =>
                Math.abs(rv.x - ax) < 20 && Math.abs(rv.y - ay) < 20
            );
            if (!dup) {
                const id  = el.id ? '#' + el.id : '';
                results.push({
                    x: ax, y: ay,
                    width:  Math.round(r.width),
                    height: Math.round(r.height),
                    selector: el.tagName.toLowerCase() + id + ' (leaderboard-iab-size)'
                });
            }
        });
    } catch(e) {}

    // =========================================================
    // SIDEBAR / RIGHT-RAIL POSITIONAL SCAN
    // Find any right-side element matching common IAB sidebar sizes
    // (300x250, 300x600, 160x600) — even without ad-specific class names.
    // =========================================================
    try {
        const IAB_SIDEBAR = [
            [300,250],[336,280],[250,250],[200,200],
            [300,600],[300,1050],[160,600],[120,600],[300,100]
        ];
        const pageW = document.documentElement.scrollWidth || window.innerWidth;
        const rightZone = pageW * 0.5;   // right half of page
        document.querySelectorAll('div, aside, section').forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width < 10 || r.height < 10) return;
            const ax = Math.round(r.left + window.scrollX);
            const ay = Math.round(r.top  + window.scrollY);
            if (ax < rightZone) return;   // must be in right half
            if (ay < 50)        return;   // skip header area
            // Must match an IAB sidebar size within 20px
            const matched = IAB_SIDEBAR.some(
                ([iw,ih]) => Math.abs(r.width-iw) <= 20 && Math.abs(r.height-ih) <= 20
            );
            if (!matched) return;
            const dup = results.some(rv =>
                Math.abs(rv.x - ax) < 20 && Math.abs(rv.y - ay) < 20
            );
            if (!dup) {
                const id  = el.id ? '#' + el.id : '';
                const cls = typeof el.className === 'string'
taskkill /PID <PID> /F                    ? '.' + el.className.trim().split(/\\s+/)[0] : '';
                results.push({
                    x: ax, y: ay,
                    width:  Math.round(r.width),
                    height: Math.round(r.height),
                    selector: el.tagName.toLowerCase() + id + cls + ' (sidebar-iab-size)'
                });
            }
        });
    } catch(e) {}

    // =========================================================
    // CSS HINT SCAN
    // Catch any ad container (by class/id keyword) that is 0×0
    // but has an explicit inline width + height style — some
    // publishers pre-size the div before the ad script fires.
    // =========================================================
    const cssHintSelectors = [
        '[id*="div-gpt-ad"]', '[id*="gpt-ad"]', '[id*="dfp-ad"]',
        '[id*="ad-slot"]',    '[id*="ad_slot"]',
        '[class*="ad-unit"]', '[class*="adUnit"]',
        '[class*="ad-slot"]', '[class*="adSlot"]'
    ];
    document.querySelectorAll(cssHintSelectors.join(',')).forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width > 10 && r.height > 10) return;

        const st = el.style;
        const pw = parseFloat(st.width  || st.minWidth  || '0');
        const ph = parseFloat(st.height || st.minHeight || '0');
        if (pw < 50 || ph < 20) return;

        const ax = Math.round(r.left + window.scrollX);
        const ay = Math.round(r.top  + window.scrollY);
        if (ay === 0 && ax === 0) return;

        const dup = results.some(r2 =>
            Math.abs(r2.x - ax) < 20 && Math.abs(r2.y - ay) < 20
        );
        if (!dup) {
            results.push({
                x: ax, y: ay,
                width: Math.round(pw), height: Math.round(ph),
                selector: el.tagName.toLowerCase() +
                    (el.id ? '#' + el.id : '') +
                    ' (css-hint-size)'
            });
        }
    });

    return results;
}
"""


# ==========================================
# NETWORK MONITORING
# ==========================================

# FIX 1: Attach network listener before page navigation.
# Call this right after page = await context.new_page(),
# before await page.goto(url).
async def attach_network_listener(page: Page) -> list:

    network_hits = []

    def handle_request(request):

        try:
            url = request.url.lower()

            for keyword in CONFIG["network_keywords"]:

                if keyword in url:

                    network_hits.append({
                        "url": url,
                        "matched_keyword": keyword
                    })

                    break

        except Exception as e:
            # FIX 2: Log instead of silently swallowing errors
            print(f"[NETWORK] Request handler error: {e}")

    page.on("request", handle_request)

    return network_hits


# ==========================================
# MAIN DETECTOR
# ==========================================

# FIX 3: Raised default min_confidence from 20 → 45
# to reduce false positives from weak keyword matches.
async def detect_ad_slots(
    page: Page,
    min_confidence: int = 30
) -> dict[str, list]:

    try:

        print("\n[AD-DETECTOR] Starting advanced scan...")

        # ----------------------------------
        # WAIT FOR NETWORK IDLE
        # FIX 4: Ensure all ad network requests
        # have fired before reading network_hits.
        # ----------------------------------

        try:
            await page.wait_for_load_state("networkidle", timeout=2000)
        except Exception:
            pass  # proceed even if network isn't fully idle    

        # ----------------------------------
        # INSTALL OBSERVER
        # NOTE: For best results, install via
        # page.add_init_script() BEFORE page.goto().
        # See usage example at bottom of file.
        # ----------------------------------

        await page.evaluate(MUTATION_OBSERVER_SCRIPT)

        # ----------------------------------
        # DOM SCAN
        # FIX 5: Selectors passed as argument, not
        # interpolated into JS string via f-string.
        # Prevents breakage if a selector contains { }.
        # ----------------------------------

        raw_slots = await page.evaluate(
            DOM_SCAN_SCRIPT,
            CONFIG["selectors"]
        )

        # ----------------------------------
        # DYNAMIC ADS
        # ----------------------------------

        dynamic_ads = await page.evaluate(
            "() => window.__dynamicAds || []"
        )

        raw_slots.extend(dynamic_ads)

        # ----------------------------------
        # REMOVE DUPLICATES
        # FIX 6: Include width + height in duplicate
        # check so same-position, different-size slots
        # are not incorrectly merged.
        # ----------------------------------

        unique_slots = []

        for slot in raw_slots:

            exists = any(

                abs(slot["x"] - s["x"]) < 5 and
                abs(slot["y"] - s["y"]) < 5 and
                abs(slot["width"] - s["width"]) < 5 and    # added
                abs(slot["height"] - s["height"]) < 5      # added

                for s in unique_slots
            )

            if not exists:
                unique_slots.append(slot)

        # ----------------------------------
        # CONFIDENCE SCORING
        # ----------------------------------

        scored_slots = [
            calculate_confidence_score(slot)
            for slot in unique_slots
        ]

        filtered_slots = [

            slot for slot in scored_slots

            if slot["confidence"] >= min_confidence
        ]

        # ----------------------------------
        # LOGGING
        # ----------------------------------

        if filtered_slots:

            print(
                f"[AD-DETECTOR] "
                f"{len(filtered_slots)} ads detected"
            )

            for i, slot in enumerate(filtered_slots):

                print(
                    f"  {i+1}. "
                    f"{slot['width']}x{slot['height']} "
                    f"at ({slot['x']}, {slot['y']}) "
                    f"| Confidence: {slot['confidence']}% "
                    f"| Reasons: {', '.join(slot['confidence_reasons'])}"
                )

        else:
            print("[AD-DETECTOR] No ads found")

        # FIX 4 (cont): network_hits is read after networkidle,
        # so the list is fully populated at this point.
        from_network = getattr(page, "_ad_network_hits", [])

        print(
            f"[NETWORK] "
            f"{len(from_network)} ad requests detected"
        )

        return {
            "slots": filtered_slots,
            "network_hits": from_network
        }

    except Exception as e:

        print(f"[AD-DETECTOR] Error: {e}")

        return {
            "slots": [],
            "network_hits": []
        }


# ==========================================
# CONFIDENCE SCORING
# ==========================================

# FIX 7: No longer mutates input dict.
# Returns a new scored copy instead.
def calculate_confidence_score(slot: dict) -> dict:

    scored = slot.copy()   # was: modifying slot in-place
    score = 0
    reasons = []

    selector = scored.get("selector", "").lower()

    # AdChoices-confirmed — real ad 100% loaded here, highest trust
    if "adchoices-confirmed" in selector:
        score += 95
        reasons.append("adchoices-confirmed")
    # GPT API-sourced slots — size is authoritative, high confidence
    elif "gpt-api-size" in selector:
        score += 60
        reasons.append("gpt-api-size")
    elif "gpt-iframe-fallback" in selector:
        score += 55
        reasons.append("gpt-iframe")
    elif "data-attr-size" in selector or "css-hint-size" in selector:
        score += 35
        reasons.append("forced-size-attr")
    # IAB positional heuristics — size matched standard ad dimensions
    elif "leaderboard-iab-size" in selector:
        score += 30
        reasons.append("leaderboard-iab")
    elif "sidebar-iab-size" in selector:
        score += 30
        reasons.append("sidebar-iab")
    elif "iab-size" in selector:
        score += 30
        reasons.append("iab-size")
    # Selector-based detection — ad class/id names present
    else:
        for kw in ("adsbygoogle", "div-gpt-ad", "doubleclick", "googlesyndication",
                   "taboola", "outbrain"):
            if kw in selector:
                score += 50
                reasons.append(f"high-confidence-kw:{kw}")
                break
        else:
            for kw in ("ad-slot", "ad-unit", "ad-container", "ad-box",
                       "adunit", "adbox", "advertisement", "sponsored"):
                if kw in selector:
                    score += 25
                    reasons.append(f"medium-kw:{kw}")
                    break

    # Bonus: exact IAB size match → high probability it's a real ad slot
    w = scored.get("width",  0)
    h = scored.get("height", 0)
    IAB_ALL = [
        (728,90),(970,90),(970,250),(468,60),   # desktop banners
        (300,250),(336,280),(250,250),(200,200), # rectangles
        (300,600),(300,1050),(160,600),(120,600),# sidebars
        (320,50),(320,100),                      # mobile
        (300,100),
    ]
    if any(abs(w - iw) <= 10 and abs(h - ih) <= 10 for iw, ih in IAB_ALL):
        score += 20
        reasons.append("exact-iab-size")

    # Bonus: large area — more likely a real ad slot
    area = w * h
    if area >= 200_000:
        score += 10
        reasons.append("large-area")
    elif area >= 60_000:
        score += 5
        reasons.append("medium-area")

    # Cap at 100
    score = min(score, 100)

    scored["confidence"]         = score
    scored["confidence_reasons"] = reasons
    return scored
