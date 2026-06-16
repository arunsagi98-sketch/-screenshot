"""
Smart Placement — Level 3 fallback when no ad slots are found on a page.

Tries three strategies in order, returning the first that succeeds:

  1. Structural DOM   — free, instant, works on any standard layout
                        Finds the header bottom (horizontal) or right
                        sidebar gap (vertical) from the DOM.

  2. Claude Vision    — AI picks the single best position on the page.
                        Only used when ANTHROPIC_API_KEY is set.
                        Cost: ~$0.001 per call (Haiku model).

  3. Native Article   — Inserts ad between article paragraphs as a
                        "Sponsored" block. Always works on editorial sites.

All three return a slot dict compatible with the existing injection pipeline:
    {"x", "y", "width", "height", "selector", "confidence",
     "confidence_reasons", "placement_type": "smart"}
"""

import asyncio
import base64
import json
import logging
import os
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def find_smart_placement(
    page: Page,
    screenshot_path: str,
    creative: dict,
) -> Optional[dict]:
    """
    Try 3 strategies to find a placement position for `creative` on `page`.
    Returns a slot dict, or None if all strategies fail.
    """
    c_w = creative["width"]
    c_h = creative["height"]

    # ── Strategy 1: Structural DOM (free, fast) ────────────────────────
    slot = await _structural_dom(page, c_w, c_h)
    if slot:
        logger.info("[SMART-PLACE] Strategy 1 (structural DOM) found: %dx%d at (%d,%d)",
                    slot["width"], slot["height"], slot["x"], slot["y"])
        return slot

    # ── Strategy 2: Claude Vision (smart, paid) ────────────────────────
    slot = await _claude_vision_place(screenshot_path, c_w, c_h)
    if slot:
        logger.info("[SMART-PLACE] Strategy 2 (Claude Vision) found: %dx%d at (%d,%d)",
                    slot["width"], slot["height"], slot["x"], slot["y"])
        return slot

    # ── Strategy 3: Native article injection (always works) ───────────
    slot = await _native_article(page, c_w, c_h)
    if slot:
        logger.info("[SMART-PLACE] Strategy 3 (native article) found: %dx%d at (%d,%d)",
                    slot["width"], slot["height"], slot["x"], slot["y"])
        return slot

    logger.info("[SMART-PLACE] All strategies exhausted — no placement found")
    return None


# ---------------------------------------------------------------------------
# Strategy 1 — Structural DOM
# ---------------------------------------------------------------------------

_STRUCTURAL_JS = """
([c_w, c_h, viewport_w, viewport_h]) => {
    const isHorizontal = c_w > c_h;

    // ── Horizontal: place just below the site header/nav ──────────────
    if (isHorizontal) {
        const navSels = [
            'header', 'nav', '[role="banner"]', '.header', '#header',
            '.site-header', '#site-header', '.navbar', '#navbar',
            '.top-bar', '.masthead'
        ];
        let navBottom = 0;
        for (const sel of navSels) {
            const el = document.querySelector(sel);
            if (el) {
                const r = el.getBoundingClientRect();
                if (r.height > 20 && r.bottom > navBottom) {
                    navBottom = r.bottom;
                }
            }
        }
        if (navBottom > 0 && navBottom + c_h + 10 < viewport_h) {
            const x = Math.round((viewport_w - c_w) / 2);
            const y = Math.round(navBottom + window.scrollY + 6);
            return { x, y, width: c_w, height: c_h,
                     reason: "below site header" };
        }

        // Fallback: just above footer
        const footSels = ['footer', '[role="contentinfo"]', '.footer', '#footer'];
        for (const sel of footSels) {
            const el = document.querySelector(sel);
            if (el) {
                const r = el.getBoundingClientRect();
                if (r.top > c_h + 20 && r.top < viewport_h) {
                    const x = Math.round((viewport_w - c_w) / 2);
                    const y = Math.round(r.top + window.scrollY - c_h - 8);
                    return { x, y, width: c_w, height: c_h,
                             reason: "above footer" };
                }
            }
        }
    }

    // ── Vertical: place in the right sidebar or right margin ──────────
    else {
        const mainSels = [
            'main', '[role="main"]', 'article', '.article-body',
            '.post-content', '.entry-content', '.content', '#content',
            '.main-content', '#main-content'
        ];
        for (const sel of mainSels) {
            const el = document.querySelector(sel);
            if (!el) continue;
            const r = el.getBoundingClientRect();
            const rightEdge = r.right + window.scrollX;

            // Is there room in the right margin?
            if (rightEdge + c_w + 20 <= viewport_w) {
                const x = Math.round(rightEdge + 16);
                const y = Math.round(r.top + window.scrollY + 10);
                if (y + c_h < viewport_h + window.scrollY) {
                    return { x, y, width: c_w, height: c_h,
                             reason: "right of main content" };
                }
            }

            // Left margin?
            const leftEdge = r.left + window.scrollX;
            if (leftEdge - c_w - 20 >= 0) {
                const x = Math.round(leftEdge - c_w - 16);
                const y = Math.round(r.top + window.scrollY + 10);
                if (y + c_h < viewport_h + window.scrollY) {
                    return { x, y, width: c_w, height: c_h,
                             reason: "left of main content" };
                }
            }
        }

        // Fallback: top-right corner (above the fold)
        const x = Math.round(viewport_w - c_w - 16);
        const y = 80;
        if (x > 0) {
            return { x, y, width: c_w, height: c_h,
                     reason: "top-right margin fallback" };
        }
    }

    return null;
}
"""

async def _structural_dom(page: Page, c_w: int, c_h: int) -> Optional[dict]:
    try:
        vp = page.viewport_size or {"width": 1440, "height": 900}
        result = await page.evaluate(_STRUCTURAL_JS, [c_w, c_h, vp["width"], vp["height"]])
        if not result:
            return None
        return _make_slot(
            result["x"], result["y"], result["width"], result["height"],
            "structural-dom-placement",
            85,
            f"Structural: {result.get('reason', 'layout gap')}",
        )
    except Exception as e:
        logger.debug("[SMART-PLACE] Structural DOM error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Strategy 2 — Claude Vision placement
# ---------------------------------------------------------------------------

_PLACE_PROMPT = """\
This webpage currently has NO advertisement slots.
Find the SINGLE best position to place a {w}x{h} {orientation} ad.

Good positions:
- Just below the header/navigation bar
- In a sidebar column gap
- Between article sections
- Above the footer

Return ONLY valid JSON, no explanation:
{{"x": 100, "y": 80, "width": {w}, "height": {h}, "reason": "below header nav"}}

Coordinates are pixels from the top-left of the image.
Only return one position — the most natural and visible one.
"""

async def _claude_vision_place(
    screenshot_path: str,
    c_w: int,
    c_h: int,
) -> Optional[dict]:
    try:
        from core.config import get_settings
        settings = get_settings()
        if not settings.anthropic_api_key:
            return None
        if not os.path.isfile(screenshot_path):
            return None

        try:
            import anthropic
        except ImportError:
            return None

        with open(screenshot_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        orientation = "horizontal banner" if c_w > c_h else "vertical rectangle"
        prompt = _PLACE_PROMPT.format(w=c_w, h=c_h, orientation=orientation)

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        def _call():
            return client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )

        response = await asyncio.to_thread(_call)
        raw = response.content[0].text.strip()

        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)
        return _make_slot(
            int(data["x"]), int(data["y"]),
            int(data.get("width", c_w)), int(data.get("height", c_h)),
            "claude-vision-placement",
            90,
            f"Claude AI: {data.get('reason', 'best visible position')}",
        )

    except Exception as e:
        logger.debug("[SMART-PLACE] Claude vision placement error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Strategy 3 — Native article injection (between paragraphs)
# ---------------------------------------------------------------------------

_NATIVE_JS = """
([c_w, c_h, viewport_h]) => {
    // Find the article body
    const bodySels = [
        'article', '.article-body', '.post-content', '.entry-content',
        '.story-body', '.article-content', '[itemprop="articleBody"]',
        'main', '[role="main"]'
    ];
    let container = null;
    for (const sel of bodySels) {
        const el = document.querySelector(sel);
        if (el && el.querySelectorAll('p').length >= 2) {
            container = el;
            break;
        }
    }
    if (!container) return null;

    // Find a paragraph after which we can insert (paragraph 2 or 3)
    const paragraphs = Array.from(container.querySelectorAll('p'))
        .filter(p => p.innerText && p.innerText.trim().length > 40);

    const targetIndex = Math.min(2, paragraphs.length - 1);
    const anchor = paragraphs[targetIndex];
    if (!anchor) return null;

    const r = anchor.getBoundingClientRect();
    // Position: centered, just below this paragraph
    const x = Math.round((window.innerWidth - c_w) / 2);
    const y = Math.round(r.bottom + window.scrollY + 12);

    // Only use if within a reasonable range (not deep below fold)
    if (y > viewport_h * 3) return null;

    return { x, y, width: c_w, height: c_h,
             reason: "after paragraph " + (targetIndex + 1) + " of article" };
}
"""

async def _native_article(page: Page, c_w: int, c_h: int) -> Optional[dict]:
    try:
        vp = page.viewport_size or {"width": 1440, "height": 900}
        result = await page.evaluate(_NATIVE_JS, [c_w, c_h, vp["height"]])
        if not result:
            return None
        return _make_slot(
            result["x"], result["y"], result["width"], result["height"],
            "native-article-placement",
            75,
            f"Native: {result.get('reason', 'between paragraphs')}",
        )
    except Exception as e:
        logger.debug("[SMART-PLACE] Native article error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_slot(
    x: int, y: int, w: int, h: int,
    selector: str, confidence: int, reason: str,
) -> dict:
    return {
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "selector": selector,
        "confidence": confidence,
        "confidence_reasons": [reason],
        "placement_type": "smart",   # marks it as a smart placement
    }
