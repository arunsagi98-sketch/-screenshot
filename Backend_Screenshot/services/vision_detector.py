"""
Claude Vision — AI-powered ad slot detection.

Sends the page screenshot to Claude and asks it to identify
all advertisement regions with their bounding boxes.

Falls back gracefully (returns []) when:
  - ANTHROPIC_API_KEY is not set
  - anthropic package is not installed
  - API call fails for any reason

Usage:
    from services.vision_detector import detect_ads_with_vision
    vision_slots = await detect_ads_with_vision(screenshot_path)
"""

import asyncio
import base64
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy import — only required if key is configured
try:
    import anthropic as _anthropic_module
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


_VISION_PROMPT = """Look at this webpage screenshot carefully.

Find every advertisement / banner ad / ad slot visible on the page.
Ads are typically: rectangular banners, sidebar rectangles, leaderboard strips at top/bottom,
inline display ads inside article content, or any clearly commercial promotional content.

For EACH ad you find, return its position and size in pixels from the top-left of the image.

Return ONLY valid JSON, no explanation:
{
  "ads": [
    {"x": 100, "y": 50, "width": 728, "height": 90,  "format": "leaderboard",  "confidence": 0.97},
    {"x": 980, "y": 120, "width": 300, "height": 250, "format": "rectangle",    "confidence": 0.94},
    {"x": 980, "y": 400, "width": 300, "height": 600, "format": "half-page",    "confidence": 0.91}
  ]
}

If no ads are visible, return: {"ads": []}

Important:
- x, y are the top-left corner coordinates in pixels
- width and height are in pixels
- confidence is 0.0–1.0 (how certain you are it is an ad)
- only include regions you are reasonably confident (> 0.7) are ads
"""


async def detect_ads_with_vision(
    screenshot_path: str,
    min_confidence: float = 0.75,
) -> list[dict]:
    """
    Send a screenshot to Claude and get ad bounding boxes back.

    Returns a list of slot dicts compatible with the existing pipeline:
        [{"x": int, "y": int, "width": int, "height": int,
          "selector": "vision-detected", "confidence": int, ...}]

    Returns [] silently if the API key is missing or the call fails.
    """
    from core.config import get_settings
    settings = get_settings()

    if not settings.anthropic_api_key:
        logger.debug("[VISION] ANTHROPIC_API_KEY not set — skipping vision detection")
        return []

    if not _ANTHROPIC_AVAILABLE:
        logger.warning("[VISION] 'anthropic' package not installed. Run: pip install anthropic")
        return []

    if not os.path.isfile(screenshot_path):
        logger.warning("[VISION] Screenshot not found: %s", screenshot_path)
        return []

    try:
        with open(screenshot_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        client = _anthropic_module.Anthropic(api_key=settings.anthropic_api_key)

        # Run synchronous client in thread so we don't block the event loop
        def _call_api():
            return client.messages.create(
                model="claude-haiku-4-5-20251001",   # fast + cheap (~$0.001/image)
                max_tokens=1024,
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
                        {
                            "type": "text",
                            "text": _VISION_PROMPT,
                        },
                    ],
                }],
            )

        response = await asyncio.to_thread(_call_api)
        raw_text = response.content[0].text.strip()

        # Extract JSON even if the model adds markdown fences
        if "```" in raw_text:
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        data = json.loads(raw_text)
        ads  = data.get("ads", [])

        # Convert to pipeline-compatible slot format
        slots = []
        for ad in ads:
            conf = float(ad.get("confidence", 0.8))
            if conf < min_confidence:
                continue
            slots.append({
                "x":          int(ad.get("x", 0)),
                "y":          int(ad.get("y", 0)),
                "width":      int(ad.get("width", 0)),
                "height":     int(ad.get("height", 0)),
                "selector":   f"vision-detected ({ad.get('format', 'ad')})",
                "confidence": int(conf * 100),
                "confidence_reasons": [f"Claude Vision {conf:.0%} confidence"],
                "source":     "vision",
            })

        logger.info("[VISION] Claude detected %d ad(s) in screenshot", len(slots))
        for s in slots:
            logger.info("[VISION]   %dx%d at (%d,%d) — %s",
                        s["width"], s["height"], s["x"], s["y"], s["selector"])

        return slots

    except json.JSONDecodeError as e:
        logger.warning("[VISION] Could not parse Claude response as JSON: %s", e)
        return []
    except Exception as e:
        logger.warning("[VISION] Vision detection failed: %s", e)
        return []
