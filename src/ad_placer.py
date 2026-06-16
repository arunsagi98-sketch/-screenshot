"""
ad_placer.py  –  Ad Placement Automation Pipeline
===================================================
• Condition 1  : AI-matched injection into detected ad slots
• Condition 2  : Fallback placement using orientation rules (A / B / C / D)
  – Rule A  Vertical   → Left-rail skyscraper (160px wide, main content gets 180px left padding)
  – Rule B  Horizontal → Top banner below nav  (100% width, max-height 90px, content pushed down)
  – Rule C  Square     → Centre-inline 300×250 box inside first content block
  – Rule D  Screenshot capture (same for A / B / C)
"""

import os
import re
import json
import base64
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from playwright.async_api import async_playwright, Page
from bs4 import BeautifulSoup
from PIL import Image

# ──────────────────────────────────────────────────────────────────────────────
# Default configuration  (merged with config.yaml at runtime)
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG: Dict = {
    "input": {
        "urls_file":  "./input/urls.txt",
        "images_dir": "./input/ad_images"
    },
    "output": {
        "base_dir":        "./output",
        "screenshots_dir": "./output/screenshots",
        "report_file":     "./output/report.json"
    },
    "browser": {
        "headless": True,
        "viewport": {"width": 1280, "height": 768}
    },
    "concurrency": 1,
    "fallback": {"min_score": 0.4},
    "ad_label_css": (
        "position:absolute;bottom:4px;right:6px;"
        "font-size:9px;font-family:sans-serif;"
        "background:rgba(255,255,255,0.85);color:#555;"
        "padding:1px 4px;border:1px solid #bbb;border-radius:2px;"
        "letter-spacing:0.3px;pointer-events:none;z-index:99999;"
    )
}

# ──────────────────────────────────────────────────────────────────────────────
# Config loader
# ──────────────────────────────────────────────────────────────────────────────
def load_config() -> Dict:
    try:
        import yaml
    except ImportError:
        return DEFAULT_CONFIG.copy()

    config_path = Path("config.yaml")
    if not config_path.is_file():
        return DEFAULT_CONFIG.copy()

    with open(config_path, "r", encoding="utf-8") as f:
        user_cfg = yaml.safe_load(f) or {}

    def deep_merge(base: Dict, override: Dict) -> Dict:
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k] = deep_merge(base[k], v)
            else:
                base[k] = v
        return base

    return deep_merge(DEFAULT_CONFIG.copy(), user_cfg)


# ──────────────────────────────────────────────────────────────────────────────
# I/O helpers
# ──────────────────────────────────────────────────────────────────────────────
def read_urls(file_path: str) -> List[str]:
    p = Path(file_path)
    if not p.is_file():
        print(f"[WARN] URLs file not found: {file_path}")
        return []
    return [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_images(images_dir: str) -> List[Path]:
    p = Path(images_dir)
    if not p.is_dir():
        print(f"[WARN] Images directory not found: {images_dir}")
        return []
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    return sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in exts)


def image_to_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def get_image_dims(path: Path) -> Tuple[int, int]:
    with Image.open(path) as img:
        return img.size  # (width, height)


def image_orientation(w: int, h: int) -> str:
    ratio = w / h if h else 0
    if ratio < 0.85:      return "vertical"
    if ratio > 1.15:      return "horizontal"
    return "square"


# ──────────────────────────────────────────────────────────────────────────────
# Ad-slot detection
# ──────────────────────────────────────────────────────────────────────────────
# Known IAB sizes: (width, height, zone_name)
IAB_SIZES = [
    (728,  90,  "leaderboard"),
    (300, 250,  "medium-rectangle"),
    (320,  50,  "mobile-banner"),
    (160, 600,  "wide-skyscraper"),
    (120, 600,  "skyscraper"),
    (970,  90,  "super-leaderboard"),
    (300, 600,  "half-page"),
    (336, 280,  "large-rectangle"),
]

AD_KEYWORDS = [
    "ad", "ads", "advert", "advertisement", "banner",
    "sponsor", "sponsored", "promo", "promotion", "adsense",
    "dfp", "gpt", "adunit", "ad-unit", "ad_unit"
]


def _has_ad_keyword(value: str) -> bool:
    val = value.lower()
    return any(kw in val for kw in AD_KEYWORDS)


def _parse_px(value: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*px", value)
    return int(m.group(1)) if m else None


def detect_slots_from_html(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    slots: List[Dict] = []

    for tag in soup.find_all(["div", "section", "aside", "ins", "iframe", "span"]):
        tag_id    = tag.get("id", "")
        tag_class = " ".join(tag.get("class", []))
        style     = tag.get("style", "")

        # Must look like an ad slot
        if not (_has_ad_keyword(tag_id) or _has_ad_keyword(tag_class)):
            continue

        # Attempt to extract width / height from style
        width  = _parse_px(style.split("width")[1].split(";")[0]) if "width" in style else None
        height = _parse_px(style.split("height")[1].split(";")[0]) if "height" in style else None

        # Fall back to IAB class names
        if not (width and height):
            for iw, ih, iname in IAB_SIZES:
                if iname in tag_class.lower():
                    width, height = iw, ih
                    break

        # Ultimate fallback: 300×250 medium rectangle
        if not (width and height):
            width, height = 300, 250

        slot_id = tag_id or tag_class.split()[0] if tag_class else "unknown"
        ar = width / height if height else 0
        ori = image_orientation(width, height)

        # Determine rough placement zone from position keywords
        zone = "unknown"
        combined = (tag_id + " " + tag_class).lower()
        if any(x in combined for x in ["top", "header", "leader"]):
            zone = "top-banner"
        elif any(x in combined for x in ["right", "sidebar", "rail-r"]):
            zone = "right-sidebar"
        elif any(x in combined for x in ["left", "rail-l", "skyscraper"]):
            zone = "left-rail"
        elif any(x in combined for x in ["footer", "bottom"]):
            zone = "footer"
        elif any(x in combined for x in ["inline", "content", "article", "mid"]):
            zone = "center-inline"

        slots.append({
            "selector": f"#{tag_id}" if tag_id else f".{tag_class.split()[0]}",
            "position": zone,
            "width":    width,
            "height":   height,
            "aspect":   ar,
            "orient":   ori,
        })

    return slots


# ──────────────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────────────
def compute_score(img_w: int, img_h: int, slot: Dict) -> float:
    slot_w, slot_h = slot["width"], slot["height"]
    img_ar  = img_w / img_h if img_h else 0
    slot_ar = slot_w / slot_h if slot_h else 0

    # Aspect-ratio score
    diff = abs(img_ar - slot_ar) / slot_ar if slot_ar else 1
    if diff <= 0.10:   ar_score = 1.0
    elif diff <= 0.25: ar_score = 0.8
    elif diff <= 0.50: ar_score = 0.5
    else:              ar_score = 0.0

    # Orientation match
    img_ori  = image_orientation(img_w, img_h)
    slot_ori = slot["orient"]
    ori_score = 1.0 if img_ori == slot_ori else 0.3

    # Size scale (image should be at least as large as the slot)
    scale = min(img_w / slot_w, img_h / slot_h) if (slot_w and slot_h) else 0
    size_score = min(1.0, scale)

    return (ar_score * 0.5) + (ori_score * 0.3) + (size_score * 0.2)


def best_match_pair(
    images: List[Path],
    used_images: set,
    slots: List[Dict],
) -> Tuple[Optional[Path], Optional[Dict], float]:
    """Return (image_path, slot, score) for the best unused image × slot pair."""
    best_img, best_slot, best_score = None, None, 0.0
    for slot in slots:
        for img_path in images:
            if img_path.name in used_images:
                continue
            w, h = get_image_dims(img_path)
            score = compute_score(w, h, slot)
            if score > best_score:
                best_score = score
                best_img   = img_path
                best_slot  = slot
    return best_img, best_slot, best_score


# ──────────────────────────────────────────────────────────────────────────────
# JavaScript injection helpers
# ──────────────────────────────────────────────────────────────────────────────
LABEL_CSS = (
    "position:absolute;bottom:4px;right:6px;"
    "font-size:9px;font-family:Arial,sans-serif;"
    "background:rgba(255,255,255,0.85);color:#555;"
    "padding:1px 4px;border:1px solid #bbb;border-radius:2px;"
    "letter-spacing:0.3px;pointer-events:none;z-index:99999;"
)


async def inject_condition1(page: Page, slot: Dict, img_path: Path, label_css: str) -> None:
    """Replace the detected ad slot element with the ad image (Condition 1)."""
    ext   = img_path.suffix.lstrip(".")
    b64   = image_to_b64(img_path)
    mime  = f"image/{'jpeg' if ext in ('jpg','jpeg') else ext}"
    selector = slot["selector"]

    js = f"""
    (function() {{
        // Find the slot element
        var el = document.querySelector({json.dumps(selector)});
        if (!el) return;

        // Wrapper: keep original dimensions, relative positioning for label
        el.style.position    = 'relative';
        el.style.overflow    = 'hidden';
        el.style.display     = 'block';
        el.style.boxSizing   = 'border-box';
        el.style.border      = '0.5px solid #e2e8f0';
        el.style.borderRadius= '4px';

        // Clear existing children
        el.innerHTML = '';

        // Ad image
        var img          = document.createElement('img');
        img.src          = 'data:{mime};base64,{b64}';
        img.style.cssText= 'display:block;width:100%;height:100%;object-fit:cover;border:none;';

        // "Ad" label
        var lbl          = document.createElement('div');
        lbl.innerText    = 'Ad';
        lbl.style.cssText= {json.dumps(label_css)};

        el.appendChild(img);
        el.appendChild(lbl);
    }})();
    """
    await page.evaluate(js)


async def inject_rule_A(page: Page, img_path: Path, label_css: str) -> None:
    """
    Rule A – Vertical image → left-rail skyscraper.
    • 160 px wide fixed block, top-aligned with first content paragraph.
    • Main content gets padding-left: 180 px so nothing overlaps.
    """
    ext  = img_path.suffix.lstrip(".")
    b64  = image_to_b64(img_path)
    mime = f"image/{'jpeg' if ext in ('jpg','jpeg') else ext}"

    js = f"""
    (function() {{
        // ------------------------------------------------------------------
        // 1. Inject global styles: main content shifts right by 180 px
        // ------------------------------------------------------------------
        var styleTag = document.createElement('style');
        styleTag.id  = '__ad_rule_a_style__';
        styleTag.textContent = `
            body {{
                position: relative !important;
            }}
            /* Push the primary content area to make room for the left rail */
            article, main, .content, .article-body,
            [class*="content"], [class*="article"], [class*="main-col"],
            [role="main"] {{
                margin-left: 180px !important;
                transition: margin-left 0.15s ease;
            }}
        `;
        document.head.appendChild(styleTag);

        // ------------------------------------------------------------------
        // 2. Find anchor: first <p> inside main content
        // ------------------------------------------------------------------
        var anchor = document.querySelector(
            'article p, main p, [role="main"] p, .content p, .article-body p'
        );
        if (!anchor) anchor = document.querySelector('p');

        // ------------------------------------------------------------------
        // 3. Build the rail block
        // ------------------------------------------------------------------
        var rail               = document.createElement('div');
        rail.id                = '__ad_left_rail__';
        rail.style.cssText     = `
            position: absolute;
            top:      ${{anchor ? anchor.getBoundingClientRect().top + window.scrollY : 120}}px;
            left:     0;
            width:    160px;
            background: #fff;
            border:   0.5px solid #e2e8f0;
            border-radius: 4px;
            overflow: hidden;
            z-index:  1000;
            box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        `;

        var img          = document.createElement('img');
        img.src          = 'data:{mime};base64,{b64}';
        img.style.cssText= 'display:block;width:160px;height:auto;object-fit:contain;';

        var lbl          = document.createElement('div');
        lbl.innerText    = 'Ad';
        lbl.style.cssText= {json.dumps(label_css)};

        rail.appendChild(img);
        rail.appendChild(lbl);
        document.body.appendChild(rail);
    }})();
    """
    await page.evaluate(js)


async def inject_rule_B(page: Page, img_path: Path, label_css: str) -> None:
    """
    Rule B – Horizontal image → full-width sticky banner BELOW the site navigation.
    Algorithm:
      1. Walk all candidate nav/header elements and pick the one whose
         bottom edge is lowest on the page but still above the main content.
      2. Insert the banner as a direct sibling immediately after that element.
      3. Measure the actual rendered banner height, then add a <style> block
         that gives every major content wrapper exactly that amount of
         padding-top so nothing shifts or overlaps.
      4. The banner is 100 % viewport width, max-height 90 px, object-fit:cover.
      5. A "Sponsored" label sits in the top-right corner of the banner.
    """
    ext  = img_path.suffix.lstrip(".")
    b64  = image_to_b64(img_path)
    mime = f"image/{'jpeg' if ext in ('jpg','jpeg') else ext}"

    js = f"""
    (function() {{

        // ── Guard: don't inject twice ──────────────────────────────────────
        if (document.getElementById('__ad_top_banner__')) return;

        // ── 1. Locate the best nav anchor ─────────────────────────────────
        //   Priority list: most-specific → least-specific
        var NAV_SELECTORS = [
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

        var navEl = null;
        for (var i = 0; i < NAV_SELECTORS.length; i++) {{
            var candidates = document.querySelectorAll(NAV_SELECTORS[i]);
            // Pick the one whose BOTTOM edge is furthest down (= the real nav bottom)
            for (var j = 0; j < candidates.length; j++) {{
                var rect = candidates[j].getBoundingClientRect();
                if (rect.height > 0) {{           // skip zero-height / hidden elements
                    if (!navEl) {{
                        navEl = candidates[j];
                    }} else {{
                        var curRect = navEl.getBoundingClientRect();
                        if (rect.bottom > curRect.bottom) navEl = candidates[j];
                    }}
                }}
            }}
            if (navEl) break;
        }}

        // ── 2. Build the banner wrapper ───────────────────────────────────
        var banner       = document.createElement('div');
        banner.id        = '__ad_top_banner__';
        banner.style.cssText = [
            'display: block',
            'width: 100%',
            'max-height: 90px',
            'overflow: hidden',
            'position: relative',
            'box-sizing: border-box',
            'margin: 0',
            'padding: 0',
            'background: #ffffff',
            'border-bottom: 1px solid #e2e8f0',
            'z-index: 8999'
        ].join(';');

        // Ad image
        var adImg        = document.createElement('img');
        adImg.src        = 'data:{mime};base64,{b64}';
        adImg.style.cssText = [
            'display: block',
            'width: 100%',
            'height: 90px',
            'object-fit: cover',
            'object-position: center center',
            'margin: 0',
            'padding: 0',
            'border: none'
        ].join(';');

        // "Sponsored" label – top-right, unobtrusive
        var lbl          = document.createElement('div');
        lbl.innerText    = 'Sponsored';
        lbl.style.cssText = [
            'position: absolute',
            'top: 4px',
            'right: 6px',
            'font-size: 9px',
            'font-family: Arial, sans-serif',
            'background: rgba(255,255,255,0.85)',
            'color: #666',
            'padding: 1px 4px',
            'border: 1px solid #bbb',
            'border-radius: 2px',
            'letter-spacing: 0.3px',
            'pointer-events: none',
            'z-index: 9000'
        ].join(';');

        banner.appendChild(adImg);
        banner.appendChild(lbl);

        // ── 3. Insert the banner right after the nav element ──────────────
        if (navEl && navEl.parentNode) {{
            navEl.parentNode.insertBefore(banner, navEl.nextSibling);
        }} else {{
            // Last resort: prepend to body
            document.body.insertBefore(banner, document.body.firstChild);
        }}

        // ── 4. Measure actual rendered height & push content down ─────────
        //   We wait one animation frame so the browser has painted the banner.
        requestAnimationFrame(function() {{
            var bannerH = banner.getBoundingClientRect().height || 90;
            var gap     = bannerH + 8;   // 8 px breathing space

            // Build a comprehensive list of content wrapper selectors.
            // We add padding-top (not margin-top) so sticky sub-navs are
            // also pushed without causing double margins.
            var style   = document.createElement('style');
            style.id    = '__ad_rule_b_style__';
            style.textContent = `
                /*
                 * Ad Rule B – push all major content containers down by
                 * the exact height of the injected banner + gap.
                 * We target only elements that are DIRECT children of <body>
                 * and are NOT the banner itself, to avoid cascading shifts.
                 */
                body > *:not(#__ad_top_banner__) {{
                    /* default shift for anything not matched below */
                }}

                /* Primary content wrappers */
                body > main,
                body > [role="main"],
                body > .main,
                body > #main,
                body > .main-content,
                body > #main-content,
                body > .page-content,
                body > #page-content,
                body > .wrapper,
                body > #wrapper,
                body > .container,
                body > #container,
                body > .content-wrap,
                body > .site-content,
                body > #site-content,
                body > article,
                body > section {{
                    padding-top: ${{gap}}px !important;
                    box-sizing: border-box !important;
                }}

                /* Fallback: if none of the above matched, shift the first
                   non-banner child (covers simple / custom layouts) */
                body > *:not(#__ad_top_banner__):not(script):not(style):nth-child(2) {{
                    margin-top: ${{gap}}px !important;
                }}
            `;
            document.head.appendChild(style);
        }});

    }})();
    """
    await page.evaluate(js)


async def inject_rule_C(page: Page, img_path: Path, label_css: str) -> None:
    """
    Rule C – Square image → 300×250 centred inline box inside first content section.
    • Content wraps below it; no float.
    • 24 px top / bottom margin.
    """
    ext  = img_path.suffix.lstrip(".")
    b64  = image_to_b64(img_path)
    mime = f"image/{'jpeg' if ext in ('jpg','jpeg') else ext}"

    js = f"""
    (function() {{
        // ------------------------------------------------------------------
        // 1. Find the first content paragraph after the headline
        // ------------------------------------------------------------------
        var anchors = document.querySelectorAll(
            'article p, main p, [role="main"] p, .content p, .article-body p'
        );
        // Pick the 2nd paragraph (after lede) or first available
        var anchor = anchors.length >= 2 ? anchors[1] : anchors[0];
        if (!anchor) anchor = document.querySelector('p');

        // ------------------------------------------------------------------
        // 2. Build the 300×250 wrapper
        // ------------------------------------------------------------------
        var wrap               = document.createElement('div');
        wrap.id                = '__ad_inline_sq__';
        wrap.style.cssText     = `
            display:       block;
            width:         300px;
            height:        250px;
            margin:        24px auto;
            overflow:      hidden;
            position:      relative;
            border:        0.5px solid #e2e8f0;
            border-radius: 4px;
            background:    #fafafa;
            box-shadow:    0 1px 4px rgba(0,0,0,0.06);
            clear:         both;
        `;

        // "Advertisement" label ABOVE the box
        var above          = document.createElement('div');
        above.innerText    = 'Advertisement';
        above.style.cssText= `
            display:     block;
            width:       300px;
            margin:      0 auto 4px;
            font-size:   10px;
            color:       #999;
            font-family: Arial, sans-serif;
            text-align:  center;
            letter-spacing: 0.5px;
        `;

        var img          = document.createElement('img');
        img.src          = 'data:{mime};base64,{b64}';
        img.style.cssText= 'display:block;width:300px;height:250px;object-fit:cover;';

        var lbl          = document.createElement('div');
        lbl.innerText    = 'Ad';
        lbl.style.cssText= {json.dumps(label_css)};

        wrap.appendChild(img);
        wrap.appendChild(lbl);

        // ------------------------------------------------------------------
        // 3. Insert above the anchor paragraph
        // ------------------------------------------------------------------
        if (anchor && anchor.parentNode) {{
            anchor.parentNode.insertBefore(above, anchor);
            anchor.parentNode.insertBefore(wrap,  anchor);
        }} else {{
            document.body.appendChild(above);
            document.body.appendChild(wrap);
        }}
    }})();
    """
    await page.evaluate(js)


# ──────────────────────────────────────────────────────────────────────────────
# Per-URL processor
# ──────────────────────────────────────────────────────────────────────────────
async def process_url(
    page:        Page,
    url:         str,
    images:      List[Path],
    used_images: set,
    cfg:         Dict,
) -> Dict:

    label_css  = cfg.get("ad_label_css", LABEL_CSS)
    min_score  = cfg.get("fallback", {}).get("min_score", 0.4)

    result: Dict = {
        "url":            url,
        "domain":         url.split("//")[-1].split("/")[0],
        "condition_used": None,
        "image_used":     None,
        "placement_zone": None,
        "match_score":    None,
        "placement_rule": None,
        "screenshot_path":None,
        "notes":          ""
    }

    # ── Load page ──────────────────────────────────────────────────────────
    try:
        await page.goto(url, wait_until="networkidle", timeout=45_000)
    except Exception as e:
        result["notes"] = f"Page load error: {e}"
        return result

    # Scroll to trigger lazy-loaded content
    await page.evaluate("""async () => {
        await new Promise(resolve => {
            let scrolled = 0;
            const step = 300;
            const id = setInterval(() => {
                scrolled += step;
                window.scrollTo(0, scrolled);
                if (scrolled >= document.body.scrollHeight) {
                    clearInterval(id);
                    resolve();
                }
            }, 80);
        });
        window.scrollTo(0, 0);   // back to top before screenshot
    }""")

    # ── Detect slots ───────────────────────────────────────────────────────
    html  = await page.content()
    slots = detect_slots_from_html(html)

    # ── Condition 1: AI-matched injection ──────────────────────────────────
    selected_img, best_slot, score = best_match_pair(images, used_images, slots)

    if selected_img and best_slot and score >= min_score:
        try:
            await inject_condition1(page, best_slot, selected_img, label_css)
            result["condition_used"] = 1
            result["image_used"]     = selected_img.name
            result["placement_zone"] = best_slot["position"]
            result["match_score"]    = round(score, 3)
        except Exception as e:
            result["notes"] += f" [Condition 1 inject error: {e}]"
            selected_img = None  # fall through to condition 2

    # ── Condition 2: Fallback placement ────────────────────────────────────
    if result["condition_used"] != 1:
        # Pick first unused image
        fallback_img: Optional[Path] = None
        for img in images:
            if img.name not in used_images:
                fallback_img = img
                break

        if fallback_img:
            w, h = get_image_dims(fallback_img)
            ori  = image_orientation(w, h)

            try:
                if ori == "vertical":                    # Rule A
                    await inject_rule_A(page, fallback_img, label_css)
                    rule = "A"; zone = "left-rail"
                elif ori == "horizontal":                # Rule B
                    await inject_rule_B(page, fallback_img, label_css)
                    rule = "B"; zone = "top-banner"
                else:                                    # Rule C  (square)
                    await inject_rule_C(page, fallback_img, label_css)
                    rule = "C"; zone = "center-inline"

                result["condition_used"] = 2
                result["image_used"]     = fallback_img.name
                result["placement_zone"] = zone
                result["placement_rule"] = rule
                selected_img             = fallback_img
                reason = "score below threshold" if slots else "no ad slots detected"
                result["notes"]          = f"Fallback Rule {rule}: {reason}."
            except Exception as e:
                result["notes"] += f" [Fallback inject error: {e}]"
        else:
            result["condition_used"] = 2
            result["placement_rule"] = "D"
            result["notes"]          = "No unused images remaining; screenshot only."

    # ── Screenshot ─────────────────────────────────────────────────────────
    scr_dir = Path(cfg["output"]["screenshots_dir"])
    scr_dir.mkdir(parents=True, exist_ok=True)

    safe = re.sub(r"[^\w\-]", "_", url.replace("https://", "").replace("http://", ""))[:80]
    scr_path = scr_dir / f"{safe}.png"

    await page.screenshot(path=str(scr_path), full_page=False)   # viewport shot
    result["screenshot_path"] = str(scr_path)

    # ── Mark image used ────────────────────────────────────────────────────
    if selected_img:
        used_images.add(selected_img.name)
        print(f"  ✓ [{result['condition_used']}] {url[:60]} → {selected_img.name} "
              f"({result['placement_zone']}) score={result['match_score']}")
    else:
        print(f"  ✗ [{result['condition_used']}] {url[:60]} → no image used")

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────
async def main() -> None:
    cfg  = load_config()
    urls = read_urls(cfg["input"]["urls_file"])
    imgs = load_images(cfg["input"]["images_dir"])

    if not urls:
        print("[ERROR] No URLs found. Add URLs to:", cfg["input"]["urls_file"])
        return
    if not imgs:
        print("[WARN]  No images found in:", cfg["input"]["images_dir"])

    print(f"\n🚀  Processing {len(urls)} URL(s) with {len(imgs)} image(s)...\n")

    used_images: set = set()
    results: List[Dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=cfg["browser"]["headless"],
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx  = await browser.new_context(
            viewport=cfg["browser"]["viewport"],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await ctx.new_page()

        for url in urls:
            try:
                res = await process_url(page, url, imgs, used_images, cfg)
            except Exception as exc:
                res = {
                    "url":             url,
                    "domain":          url.split("//")[-1].split("/")[0],
                    "condition_used":  None,
                    "image_used":      None,
                    "placement_zone":  None,
                    "match_score":     None,
                    "placement_rule":  None,
                    "screenshot_path": None,
                    "notes":           f"Unhandled error: {exc}"
                }
                print(f"  ✗ ERROR on {url}: {exc}")
            results.append(res)

        await browser.close()

    # ── Write report ───────────────────────────────────────────────────────
    report_path = Path(cfg["output"]["report_file"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n✅  Done!  Report → {report_path}")
    print(f"📸  Screenshots → {cfg['output']['screenshots_dir']}\n")


if __name__ == "__main__":
    asyncio.run(main())
