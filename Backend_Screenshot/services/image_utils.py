import io
import json
import os
import base64
from PIL import Image


# ==========================================
# SITE → CREATIVE MAPPING
# ==========================================

_SITE_CREATIVES_CONFIG: dict | None = None

def _load_site_config() -> dict:
    """Load site_creatives.json once and cache it."""
    global _SITE_CREATIVES_CONFIG
    if _SITE_CREATIVES_CONFIG is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "site_creatives.json",
        )
        if os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                # Strip comment keys
                _SITE_CREATIVES_CONFIG = {
                    k: v for k, v in raw.items() if not k.startswith("_comment")
                }
                print(f"[IMAGE-UTILS] Loaded site_creatives.json — {len(_SITE_CREATIVES_CONFIG)} entries")
            except Exception as e:
                print(f"[IMAGE-UTILS] Could not load site_creatives.json: {e}")
                _SITE_CREATIVES_CONFIG = {}
        else:
            _SITE_CREATIVES_CONFIG = {}
    return _SITE_CREATIVES_CONFIG


def get_creatives_for_domain(domain: str, device: str = "desktop") -> list:
    """
    Return creatives for a specific domain based on site_creatives.json.

    Lookup order:
      1. Exact domain match  (e.g. "tomsguide.com")
      2. Partial match       (e.g. config key "toms" matches "tomsguide.com")
      3. "default" key       (fallback list — empty = use ALL creatives)
      4. All creatives        (if no default key either)

    Returns a list of creative dicts (same format as get_local_creatives).
    """
    config  = _load_site_config()
    # Normalise domain — strip www. prefix
    clean   = domain.lower().replace("www.", "")

    matched_filenames: list[str] | None = None

    # 1. Exact match
    if clean in config:
        matched_filenames = config[clean]
    else:
        # 2. Partial match — config key is a substring of the domain
        for key, filenames in config.items():
            if key in ("default",) or key.startswith("_"):
                continue
            if key.lower() in clean:
                matched_filenames = filenames
                print(f"[IMAGE-UTILS] Domain '{clean}' matched config key '{key}'")
                break

    # 3. Default fallback
    if matched_filenames is None:
        matched_filenames = config.get("default", [])

    # 4. Empty list → use ALL creatives (no restriction)
    if not matched_filenames:
        print(f"[IMAGE-UTILS] No specific creative mapping for '{clean}' — using all creatives")
        return get_local_creatives(device=device)

    # Load only the specified creatives
    all_creatives = get_local_creatives(device=device)
    filtered = [c for c in all_creatives if c["name"] in matched_filenames]

    if not filtered:
        print(f"[IMAGE-UTILS] Mapped filenames {matched_filenames} not found — using all creatives")
        return all_creatives

    print(f"[IMAGE-UTILS] Domain '{clean}' → {len(filtered)} creative(s): {[c['name'] for c in filtered]}")
    return filtered


# ==========================================
# HELPERS
# ==========================================

def _slot_orientation(w, h):
    """Return 'vertical', 'horizontal', or 'square' for any (w, h) pair."""
    r = w / h if h > 0 else 1.0
    if r < 0.8:
        return "vertical"
    if r > 1.2:
        return "horizontal"
    return "square"


# ==========================================
# CREATIVE LOADER
# ==========================================

def get_local_creatives(directory=None, device="desktop"):
    """
    Scans the directory for images and returns a list of dictionaries with
    metadata and base64 encoded content.

    device — "mobile" | "desktop".
      Loads from input_images/mobile/ or input_images/desktop/ subfolder if it
      exists and contains images; falls back to the flat input_images/ root
      so existing setups keep working without any file moves.
    """
    if directory is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        root_dir = os.path.join(base_dir, "input_images")
        # Prefer device-specific subfolder when it has images
        subfolder = os.path.join(root_dir, device)
        if os.path.isdir(subfolder) and any(
            f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif'))
            for f in os.listdir(subfolder)
        ):
            directory = subfolder
        else:
            directory = root_dir

    creatives = []
    supported_extensions = ('.png', '.jpg', '.jpeg', '.webp', '.gif')

    print(f"[IMAGE-UTILS] Scanning creatives folder: {directory}")

    if not os.path.exists(directory):
        os.makedirs(directory)
        return []

    for filename in os.listdir(directory):
        if filename.lower().endswith(supported_extensions):
            path = os.path.join(directory, filename)
            try:
                with Image.open(path) as img:
                    width, height = img.size
                    image_format = (img.format or "jpeg").lower()

                    if height > width:
                        orientation = "vertical"
                    elif width > height:
                        orientation = "horizontal"
                    else:
                        orientation = "square"

                with open(path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

                creatives.append({
                    "name": filename,
                    "width": width,
                    "height": height,
                    "aspect_ratio": width / height if height > 0 else 1.0,
                    "orientation": orientation,
                    "base64": f"data:image/{image_format};base64,{encoded_string}"
                })
                print(f"[IMAGE-UTILS] Loaded creative: {filename} ({width}x{height}) - {orientation}")

            except Exception as e:
                print(f"[IMAGE-UTILS] Error loading {filename}: {e}")

    print(f"[IMAGE-UTILS] Loaded {len(creatives)} creatives from {directory}")
    return creatives


# ==========================================
# SCORING COMPONENTS
# ==========================================

def calculate_aspect_ratio_score(image_ratio, slot_ratio):
    """
    Score based on aspect ratio compatibility.
    1.0 = exact match, decreasing toward 0 as ratios diverge.
    """
    if slot_ratio == 0:
        return 0.0

    ratio_diff = abs(image_ratio - slot_ratio) / slot_ratio

    if ratio_diff <= 0.05:
        return 1.0
    elif ratio_diff <= 0.10:
        return 0.85
    elif ratio_diff <= 0.25:
        return 0.60
    elif ratio_diff <= 0.40:
        return 0.30
    else:
        return 0.0


def calculate_size_score(image_w, image_h, slot_w, slot_h):
    """
    Score based on size compatibility.
    Ideal range: creative within ±20% of slot dimensions.
    """
    if slot_w == 0 or slot_h == 0:
        return 0.0

    w_ratio = image_w / slot_w if slot_w > 0 else 0
    h_ratio = image_h / slot_h if slot_h > 0 else 0

    w_score = 1.0 if 0.8 <= w_ratio <= 1.2 else max(0, 1.0 - abs(w_ratio - 1.0) * 0.5)
    h_score = 1.0 if 0.8 <= h_ratio <= 1.2 else max(0, 1.0 - abs(h_ratio - 1.0) * 0.5)

    return (w_score + h_score) / 2.0


def calculate_orientation_score(image_orientation, slot_width, slot_height):
    """
    Score based on orientation alignment.
    FIX: Cross-orientation is now strongly penalised (0.05) instead of 0.40.
    A vertical creative in a horizontal slot (or vice versa) almost never works.
    """
    slot_ratio         = slot_width / slot_height if slot_height > 0 else 1.0
    is_slot_vertical   = slot_ratio < 0.8
    is_slot_horizontal = slot_ratio > 1.2
    is_slot_square     = 0.8 <= slot_ratio <= 1.2

    if image_orientation == "vertical"   and is_slot_vertical:   return 0.95
    if image_orientation == "horizontal" and is_slot_horizontal:  return 0.95
    if image_orientation == "square"     and is_slot_square:      return 0.95
    if image_orientation == "square":                              return 0.75

    # FIX: was 0.40 — strong penalty for cross-orientation mismatch
    return 0.05


def calculate_iab_match_score(slot_width, slot_height, image_w, image_h):
    """
    Bonus when both the slot AND the creative are standard IAB sizes
    AND share the same orientation.

    FIX: Previously awarded 0.90 regardless of orientation, so a 160x600
    creative scored 0.90 against a 728x90 slot. Now returns 0.0 whenever
    the slot and creative orientations differ.
    """
    IAB_SIZES = [
        (728, 90),
        (300, 250),
        (160, 600),
        (300, 600),
        (320, 50),
        (320, 100),   # mobile large banner
        (970, 250),
        (468, 60),
    ]

    # Find which IAB format the slot matches (exact match required)
    slot_iab_match = None
    for w, h in IAB_SIZES:
        if abs(slot_width - w) <= 5 and abs(slot_height - h) <= 5:
            slot_iab_match = (w, h)
            break
        if abs(slot_width - h) <= 5 and abs(slot_height - w) <= 5:
            slot_iab_match = (h, w)
            break
    if not slot_iab_match:
        return 0.0

    # Creative must match the SAME IAB format — not just any IAB size.
    # 728x90 Leaderboard ≠ 970x250 Billboard even though both are horizontal.
    sw, sh = slot_iab_match
    creative_matches_same = (
        abs(image_w - sw) <= 5 and abs(image_h - sh) <= 5
    )
    if not creative_matches_same:
        return 0.0

    return 0.90


# ==========================================
# MAIN MATCHER
# ==========================================

def find_best_match(ad_slot, creatives, tolerance=20):
    """
    Find the best matching creative for an ad slot.

    Pass 1 (tolerance < 50):
        Strict pixel-size match first.  Falls through to composite scoring
        only when nothing fits within tolerance.

    Pass 2 (tolerance >= 50):
        Pure composite scoring with orientation gate and 0.50 threshold
        (~80 % real-world confidence).

    Scoring weights:
        aspect ratio  40 %
        size match    30 %
        orientation   20 %
        IAB bonus     10 %
    """
    if not creatives:
        return None

    slot_w      = ad_slot.get('width',  0)
    slot_h      = ad_slot.get('height', 0)
    slot_orient = _slot_orientation(slot_w, slot_h)

    # ------------------------------------------------------------------
    # PASS 1 — strict pixel-size match
    # ------------------------------------------------------------------
    if tolerance < 50:
        print(
            f"[IMAGE-UTILS] PASS1 strict match for slot {slot_w}x{slot_h} "
            f"({slot_orient}), tolerance={tolerance}"
        )
        for creative in creatives:
            w_diff = abs(creative['width']  - slot_w)
            h_diff = abs(creative['height'] - slot_h)
            if w_diff <= tolerance and h_diff <= tolerance:
                result = creative.copy()
                result['match_score'] = 0.9
                print(f"[IMAGE-UTILS] PASS1 strict hit: {creative['name']} "
                      f"({creative['width']}x{creative['height']})")
                return result

        print(f"[IMAGE-UTILS] No strict size match — falling back to composite scoring")

    # ------------------------------------------------------------------
    # Composite scoring  (Pass 2, or Pass 1 fallback)
    # ------------------------------------------------------------------
    slot_ratio    = slot_w / slot_h if slot_h > 0 else 1.0
    best_score    = -1.0
    best_creative = None

    for creative in creatives:
        image_w         = creative['width']
        image_h         = creative['height']
        image_ratio     = creative['aspect_ratio']
        orientation     = creative['orientation']
        creative_orient = _slot_orientation(image_w, image_h)

        # FIX: Hard skip when orientations are completely opposite.
        # Vertical creative  → horizontal slot: impossible fit, skip.
        # Horizontal creative → vertical slot:  impossible fit, skip.
        # Square creatives pass through — they can work in either.
        if (slot_orient == "vertical"   and creative_orient == "horizontal") or \
           (slot_orient == "horizontal" and creative_orient == "vertical"):
            print(
                f"[IMAGE-UTILS] Skipping {creative['name']} "
                f"({image_w}x{image_h} {creative_orient}) — "
                f"orientation mismatch with slot {slot_w}x{slot_h} ({slot_orient})"
            )
            continue

        # Component scores
        aspect_score = calculate_aspect_ratio_score(image_ratio, slot_ratio)

        # Hard gate: aspect ratio mismatch means a fundamentally wrong size.
        # 728x90 vs 970x250 gives aspect=0.0 — skip regardless of other scores.
        if aspect_score == 0.0:
            print(
                f"[IMAGE-UTILS] Skipping {creative['name']} "
                f"({image_w}x{image_h}) — aspect ratio too different from "
                f"slot {slot_w}x{slot_h} (aspect_score=0.0)"
            )
            continue

        size_score        = calculate_size_score(image_w, image_h, slot_w, slot_h)
        orientation_score = calculate_orientation_score(orientation, slot_w, slot_h)
        iab_score         = calculate_iab_match_score(slot_w, slot_h, image_w, image_h)

        composite_score = (
            aspect_score      * 0.40 +
            size_score        * 0.30 +
            orientation_score * 0.20 +
            iab_score         * 0.10
        )

        print(
            f"[IMAGE-UTILS] Scoring {creative['name']} ({image_w}x{image_h} {creative_orient}) "
            f"vs slot {slot_w}x{slot_h} ({slot_orient}): "
            f"aspect={aspect_score:.2f}, size={size_score:.2f}, "
            f"orient={orientation_score:.2f}, iab={iab_score:.2f}, "
            f"total={composite_score:.2f}"
        )

        if composite_score > best_score:
            best_score    = composite_score
            best_creative = creative

    # FIX: Threshold raised from 0.40 → 0.50.
    # 0.50 maps to roughly 80 % real-world confidence after the orientation
    # gate is in place.  Raise to 0.60 if you want to be even stricter.
    if best_score >= 0.50:
        print(f"[IMAGE-UTILS] Best match: {best_creative['name']} (score: {best_score:.2f})")
        result = best_creative.copy()
        result['match_score'] = best_score
        return result

    print(f"[IMAGE-UTILS] No acceptable match found (best score: {best_score:.2f})")
    return None


# ==========================================
# AUTO-RESIZE
# ==========================================

def _smart_contain(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    Contain mode — like CSS object-fit: contain.

    Scale the image DOWN so it fits fully inside the slot,
    then center it on a transparent background.

    Result: full creative always visible — nothing cropped, nothing distorted.
    """
    src_w, src_h = img.size

    # Scale to fill slot — upscale small creatives AND downscale large ones.
    # Removed the 1.0 cap so a 100x50 creative properly fills a 300x250 slot
    # instead of appearing tiny in the corner.
    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))

    # Resize to fit
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # Place on transparent canvas, centered
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    offset_x = (target_w - new_w) // 2
    offset_y = (target_h - new_h) // 2
    canvas.paste(resized, (offset_x, offset_y))
    return canvas


def resize_creative_for_slot(creative: dict, slot_w: int, slot_h: int) -> dict:
    """
    Smart-crop ANY creative to exactly fit the slot dimensions.
    Uses center-crop (object-fit: cover) so the image never looks
    stretched or distorted — always clean and professional.

    Returns a new creative dict with updated base64, width, height.
    Original creative dict is not modified.
    """
    try:
        # Decode base64 image
        b64_data = creative["base64"]
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]
        img_bytes = base64.b64decode(b64_data)

        # Open and contain-fit (full creative visible, no cropping)
        img        = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        result_img = _smart_contain(img, slot_w, slot_h)

        # Re-encode as PNG
        buffer = io.BytesIO()
        result_img.save(buffer, format="PNG")
        buffer.seek(0)
        encoded = base64.b64encode(buffer.read()).decode("utf-8")

        result = creative.copy()
        result["base64"]       = f"data:image/png;base64,{encoded}"
        result["width"]        = slot_w
        result["height"]       = slot_h
        result["aspect_ratio"] = slot_w / slot_h if slot_h > 0 else 1.0
        result["match_score"]  = 0.75
        result["auto_resized"] = True

        print(f"[IMAGE-UTILS] Contain-fit '{creative['name']}' "
              f"({creative['width']}x{creative['height']}) → {slot_w}x{slot_h} (nothing cropped)")
        return result

    except Exception as exc:
        print(f"[IMAGE-UTILS] resize_creative_for_slot error: {exc}")
        return None
