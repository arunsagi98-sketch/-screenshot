"""
CRM Excel processor — core row-level logic.

Python port of the n8n JS workflow. No HTTP or DB concerns here;
all I/O (file read, DB memory, file write) is handled by the router.

Public API:
    process_rows(rows, yesterday_memory, global_min_ctr, global_max_ctr, campaign_ctr_rules)
        → (output_rows, today_snapshot)
"""
from __future__ import annotations

import math
import random
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ── Output column order (must match excel_writer) ────────────────────────────
OUTPUT_COLUMNS: List[str] = [
    "Advertiser", "Advertiser ID", "Advertiser Currency",
    "Insertion Order", "Insertion Order ID",
    "Line Item", "Line Item ID",
    "Date", "Campaign", "Campaign ID",
    "Impressions", "Billable Impressions",
    "Clicks", "Click Rate (CTR)",
    "Revenue (Adv Currency)", "Media Cost (Advertiser Currency)",
    "Start Views", "1st Quartile Views", "Midpoint Views",
    "3rd Quartile Views", "Complete Views", "Video Completion Rate",
    "Viewable Impressions", "Measurable Impressions", "Viewability",
    "For Checking (Measurable-Impression)", "Start Views-Impression",
]


# ── Safe numeric helpers ──────────────────────────────────────────────────────
def safe_int(val: Any) -> int:
    if val is None or str(val).strip() in ("", "nan", "NaN", "None", "NaT"):
        return 0
    try:
        return int(float(str(val)))
    except (ValueError, TypeError):
        return 0


# ── Date normalisation ────────────────────────────────────────────────────────
def excel_serial_to_date_string(serial: float) -> str:
    """Convert Windows Excel date serial (days since 1900-01-00) → DD/MM/YYYY."""
    dt = datetime.utcfromtimestamp((serial - 25569) * 86400)
    return dt.strftime("%d/%m/%Y")


def normalize_date_string(val: str) -> str:
    """Normalise YYYY-MM-DD or D/M/YYYY variants → DD/MM/YYYY."""
    s = val.strip()
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        return f"{m.group(3).zfill(2)}/{m.group(2).zfill(2)}/{m.group(1)}"
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", s)
    if m:
        return f"{m.group(1).zfill(2)}/{m.group(2).zfill(2)}/{m.group(3)}"
    return s


def parse_date_field(raw: Any) -> Any:
    """Return DD/MM/YYYY string from an Excel serial int or a date string."""
    if raw is None or str(raw).strip() == "":
        return raw
    try:
        n = float(raw)
        if not math.isnan(n):
            return excel_serial_to_date_string(n)
    except (ValueError, TypeError):
        pass
    return normalize_date_string(str(raw))


# ── Gap enforcement (Measurable / Start Views vs Impressions) ─────────────────
def get_gap_range(impressions: int) -> Tuple[int, int]:
    """Return (min_gap, max_gap) based on impression volume."""
    if impressions < 500:
        return (1, 20)
    elif impressions <= 3000:
        return (50, 100)
    else:
        return (100, 200)


def enforce_gap(value: int, impressions: int) -> int:
    """
    Ensure `value` is within [impressions - max_gap, impressions - min_gap].
    Returns 0 unchanged if value is 0 (no video / no measurable).
    """
    if value == 0:
        return 0
    min_gap, max_gap = get_gap_range(impressions)
    gap = value - impressions
    if -max_gap <= gap <= -min_gap:
        return value
    forced_gap = random.randint(min_gap, max_gap)
    return max(0, impressions - forced_gap)


# ── Rule lookup ───────────────────────────────────────────────────────────────
def _normalize_lid(val: Any) -> str:
    """Normalise a Line Item ID: strip, drop trailing '.0', lower."""
    s = str(val).strip().split("|")[0].strip()
    if s.endswith(".0") and s[:-2].lstrip("-").isdigit():
        s = s[:-2]
    return s.lower()


def _find_rule(row: dict, campaign_ctr_rules: dict) -> dict:
    """
    Priority (most specific first):
      1. Exact Line Item ID
      2. Line Item name
      3. Full key  "li_id|li_name"
      4. Campaign name
      5. Campaign ID (numeric)
    """
    li_id   = _normalize_lid(row.get("Line Item ID") or "")
    li_name = str(row.get("Line Item") or "").strip().lower()
    li_full = f"{li_id}|{li_name}" if li_id and li_name else ""
    camp    = str(row.get("Campaign") or "").strip().lower()
    camp_id = _normalize_lid(row.get("Campaign ID") or "")

    for key in [li_id, li_name, li_full, camp, camp_id]:
        if key and key in campaign_ctr_rules:
            return campaign_ctr_rules[key]
    return {}


def _metric_bounds(
    rule: dict,
    min_key: str,
    max_key: str,
    default_min: float = 75.0,
    default_max: float = 89.0,
) -> Tuple[float, float]:
    """Return (lo, hi) as fractions (e.g. 0.75, 0.89) from rule or defaults."""
    lo = rule.get(min_key)
    hi = rule.get(max_key)
    lo = default_min if lo is None else float(lo)
    hi = default_max if hi is None else float(hi)
    if lo > hi:
        hi = lo
    return lo / 100, hi / 100


# ── Main pipeline ─────────────────────────────────────────────────────────────
def process_rows(
    rows: List[dict],
    yesterday_memory: Dict[str, List[dict]],
    global_min_ctr: float = 0.37,
    global_max_ctr: float = 0.55,
    campaign_ctr_rules: Optional[Dict[str, dict]] = None,
) -> Tuple[List[dict], Dict[str, List[dict]]]:
    """
    Process a list of row dicts in-place and return:
      (output_rows, today_snapshot)

    yesterday_memory: {line_item_id: [{"clicks": int, "ctr": "0.40%"}, ...]}
    campaign_ctr_rules: {lookup_key_lower: {"min_ctr": float, "max_ctr": float, ...}}
    today_snapshot: same shape as yesterday_memory — caller persists it to DB.
    """
    if campaign_ctr_rules is None:
        campaign_ctr_rules = {}
    if not rows:
        return [], {}

    original_keys = list(rows[0].keys())
    for i, row in enumerate(rows):
        row["_originalIndex"] = i

    # ── Date normalisation ───────────────────────────────────────────────────
    for row in rows:
        raw = row.get("Date")
        if raw is not None and str(raw).strip():
            row["Date"] = parse_date_field(raw)

    # ── Step 1: CTR ──────────────────────────────────────────────────────────
    for row in rows:
        impressions = safe_int(row.get("Impressions"))
        line_id     = _normalize_lid(row.get("Line Item ID") or "")
        rule        = _find_rule(row, campaign_ctr_rules)

        _min = rule.get("min_ctr")
        _max = rule.get("max_ctr")
        min_pct = global_min_ctr if _min is None else float(_min)
        max_pct = global_max_ctr if _max is None else float(_max)

        if impressions <= 0:
            row["Clicks"] = 0
            row["Click Rate (CTR)"] = "0.00%"
            row["_min"] = 0
            row["_max"] = 0
            continue

        min_clicks = math.ceil((min_pct / 100) * impressions)
        max_clicks = math.floor((max_pct / 100) * impressions)

        if max_clicks < min_clicks:
            best = max(1, round(((min_pct + max_pct) / 2 / 100) * impressions))
            row["Clicks"] = best
            row["Click Rate (CTR)"] = f"{(best / impressions * 100):.2f}%"
            row["_min"] = best
            row["_max"] = best
            continue

        prev_entries = yesterday_memory.get(line_id, [])

        def _is_dupe(clicks: int, imp: int = impressions, prev: list = prev_entries) -> bool:
            if not prev:
                return False
            this_ctr = f"{(clicks / imp * 100):.2f}%"
            return any(p["clicks"] == clicks or p["ctr"] == this_ctr for p in prev)

        # Try up to 150 times to pick a value not in yesterday's memory
        selected = min_clicks
        found = False
        for _ in range(150):
            candidate = random.randint(min_clicks, max_clicks)
            if not _is_dupe(candidate):
                selected = candidate
                found = True
                break

        if not found:
            # Range fully exhausted by yesterday's memory —
            # pick the click count whose CTR is most different from all yesterday CTRs
            prev_ctrs = {p["ctr"] for p in prev_entries}
            prev_clicks_set = {p["clicks"] for p in prev_entries}
            best_candidate = None
            for c in range(min_clicks, max_clicks + 1):
                if c not in prev_clicks_set:
                    best_candidate = c
                    break
            selected = best_candidate if best_candidate is not None else random.randint(min_clicks, max_clicks)

        row["Clicks"] = selected
        row["Click Rate (CTR)"] = f"{(selected / impressions * 100):.2f}%"
        row["_min"] = min_clicks
        row["_max"] = max_clicks

    # ── Step 2: De-duplicate within each Line Item group ─────────────────────
    grouped: Dict[str, list] = {}
    for row in rows:
        lid = _normalize_lid(row.get("Line Item ID") or "UNKNOWN")
        grouped.setdefault(lid, []).append(row)

    for line_id, group in grouped.items():
        prev_entries = yesterday_memory.get(line_id, [])
        used_clicks = {p["clicks"] for p in prev_entries}
        used_ctrs   = {p["ctr"]    for p in prev_entries}
        last_click: Optional[int] = None

        group.sort(key=lambda r: safe_int(r.get("Impressions")))

        for row in group:
            current_click = row["Clicks"]
            mn = row["_min"]
            mx = row["_max"]
            impressions = safe_int(row.get("Impressions"))

            if mn == 0 and mx == 0:
                used_clicks.add(current_click)
                last_click = current_click
                continue

            current_ctr = (
                f"{(current_click / impressions * 100):.2f}%"
                if impressions > 0 else "0.00%"
            )
            # Sequential gap: require at least 2 apart when the range is wide enough
            _seq_gap = 2 if (mx - mn) >= 4 else 1
            needs_change = (
                current_click in used_clicks
                or current_ctr in used_ctrs
                or (last_click is not None and abs(current_click - last_click) <= _seq_gap)
            )

            if needs_change:
                new_click = current_click
                new_ctr   = current_ctr
                for _ in range(150):
                    new_click = random.randint(mn, mx)
                    new_ctr   = (
                        f"{(new_click / impressions * 100):.2f}%"
                        if impressions > 0 else "0.00%"
                    )
                    if (
                        new_click not in used_clicks
                        and new_ctr not in used_ctrs
                        and (last_click is None or abs(new_click - last_click) > _seq_gap)
                    ):
                        break
                else:
                    # All values exhausted (very tight range) —
                    # relax sequential constraint, just avoid exact yesterday duplicates
                    for c in range(mn, mx + 1):
                        c_ctr = f"{(c / impressions * 100):.2f}%" if impressions > 0 else "0.00%"
                        if c not in used_clicks and c_ctr not in used_ctrs:
                            new_click = c
                            new_ctr   = c_ctr
                            break
                current_click = new_click
                row["Clicks"] = current_click
                row["Click Rate (CTR)"] = (
                    f"{(current_click / impressions * 100):.2f}%"
                    if impressions > 0 else "0.00%"
                )

            used_clicks.add(current_click)
            used_ctrs.add(
                f"{(current_click / impressions * 100):.2f}%"
                if impressions > 0 else "0.00%"
            )
            last_click = current_click

    rows.sort(key=lambda r: r["_originalIndex"])

    # Restore any original keys that may have been dropped
    for row in rows:
        for key in original_keys:
            if key not in row:
                row[key] = ""

    for row in rows:
        row.pop("_min", None)
        row.pop("_max", None)
        row.pop("_originalIndex", None)

    # Build today's snapshot for DB persistence (caller's job)
    today_snapshot: Dict[str, List[dict]] = {}
    for row in rows:
        lid = _normalize_lid(row.get("Line Item ID") or "")
        if not lid:
            continue
        clicks = safe_int(row.get("Clicks"))
        ctr    = str(row.get("Click Rate (CTR)") or "").strip()
        today_snapshot.setdefault(lid, []).append({"clicks": clicks, "ctr": ctr})

    # ── Step 3: Video metrics (VCR) and Viewability ──────────────────────────
    for row in rows:
        row["_originalSV"] = safe_int(row.get("Start Views"))

    for row in rows:
        rule        = _find_rule(row, campaign_ctr_rules)
        vcr_min, vcr_max   = _metric_bounds(rule, "min_vcr",         "max_vcr")
        view_min, view_max = _metric_bounds(rule, "min_viewability",  "max_viewability")
        impressions = safe_int(row.get("Impressions"))

        row.setdefault("Video Completion Rate", "0.00%")
        row.setdefault("Viewability",           "0.00%")

        start_views    = safe_int(row.get("Start Views"))
        complete_views = safe_int(row.get("Complete Views"))

        # VCR
        if start_views == 0:
            row["Video Completion Rate"] = "0.00%"
        else:
            start_views = enforce_gap(start_views, impressions)
            row["Start Views"] = start_views
            vcr = complete_views / start_views if start_views > 0 else 0

            if not (vcr_min <= vcr <= vcr_max):
                min_gap, max_gap = get_gap_range(impressions)
                sv_min = max(1, impressions - max_gap)
                sv_max = max(1, impressions - min_gap)
                new_sv = start_views
                if sv_max >= sv_min and impressions > 0:
                    new_sv = random.randint(sv_min, sv_max)
                cv_min = math.ceil(vcr_min * new_sv)
                cv_max = math.floor(vcr_max * new_sv)
                if cv_max >= cv_min:
                    new_cv = random.randint(cv_min, cv_max)
                else:
                    new_cv = max(0, round(((vcr_min + vcr_max) / 2) * new_sv))
                row["Start Views"]    = new_sv
                row["Complete Views"] = new_cv
                start_views    = new_sv
                complete_views = new_cv

            final_vcr = (complete_views / start_views * 100) if start_views > 0 else 0
            row["Video Completion Rate"] = f"{final_vcr:.2f}%"

        # Viewability
        measurable = safe_int(row.get("Measurable Impressions"))
        viewable   = safe_int(row.get("Viewable Impressions"))
        measurable = enforce_gap(measurable, impressions)
        row["Measurable Impressions"] = measurable

        viewability = viewable / measurable if measurable > 0 else 0
        if measurable > 0 and not (view_min <= viewability <= view_max):
            min_gap, max_gap = get_gap_range(impressions)
            mi_min = max(1, impressions - max_gap)
            mi_max = max(1, impressions - min_gap)
            new_m  = measurable
            if mi_max >= mi_min and impressions > 0:
                new_m = random.randint(mi_min, mi_max)
            vi_min = math.ceil(view_min * new_m)
            vi_max = math.floor(view_max * new_m)
            if vi_max >= vi_min:
                new_v = random.randint(vi_min, vi_max)
            else:
                new_v = max(0, round(((view_min + view_max) / 2) * new_m))
            row["Measurable Impressions"] = new_m
            row["Viewable Impressions"]   = new_v
            measurable = new_m
            viewable   = new_v

        final_view = (viewable / measurable * 100) if measurable > 0 else 0
        row["Viewability"] = f"{final_view:.2f}%"

    # ── Step 4: Build final output rows ──────────────────────────────────────
    output: List[dict] = []
    for row in rows:
        impressions      = safe_int(row.get("Impressions"))
        measurable_after = safe_int(row.get("Measurable Impressions"))
        start_after      = safe_int(row.get("Start Views"))
        original_sv      = safe_int(row.get("_originalSV"))

        row["For Checking (Measurable-Impression)"] = (
            0 if measurable_after == 0
            else measurable_after - impressions
        )
        row["Start Views-Impression"] = (
            start_after - impressions
            if (original_sv != 0 and impressions != 0)
            else 0
        )
        row.pop("_originalSV", None)

        new_row: dict = {}
        for col in OUTPUT_COLUMNS:
            val = row.get(col)
            if col == "Date":
                new_row[col] = str(val) if val is not None else None
            elif isinstance(val, str):
                new_row[col] = val.strip() or None
            else:
                new_row[col] = val
        output.append(new_row)

    return output, today_snapshot
