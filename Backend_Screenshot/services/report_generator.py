# -*- coding: utf-8 -*-
"""
report_generator.py
===================
Ported from Flask App.py → FastAPI service.
Generates a multi-sheet Excel report from campaign data.

Sheets produced:
  REACH / DATE / APP URL / TIME OF DAY / EXCHANGE / DEVICE /
  CREATIVE / CITY / AGE / GENDER
"""

from __future__ import annotations

import io
import math
import random
import re
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.errors import IgnoredError

from database.crm_db import crm_engine

# ---------------------------------------------------------------------------
# DB connection (ctr_db — credentials come from .env via crm_engine)
# ---------------------------------------------------------------------------

def _get_conn():
    """Return a raw DBAPI connection from the shared crm_engine (no hardcoded creds)."""
    return crm_engine.raw_connection()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_urls_from_sheets(sheet_names: list[str]) -> list[str]:
    """Return distinct cleaned URLs from app_url_reference for given sheets."""
    if not sheet_names:
        return []
    try:
        conn = _get_conn()
        cur  = conn.cursor()
        placeholders = ",".join(["%s"] * len(sheet_names))
        cur.execute(
            f"SELECT DISTINCT url FROM app_url_reference WHERE sheet_name IN ({placeholders}) ORDER BY url",
            sheet_names,
        )
        urls = [row[0] for row in cur.fetchall()]
        cur.close(); conn.close()
        return urls
    except Exception as e:
        print(f"[DB] get_urls_from_sheets failed: {e}")
        return []


def load_city_db_sheet(sheet_names: list[str]) -> list[dict]:
    """Return (city_name, weight) dicts from city_reference for given sheets."""
    if not sheet_names:
        return []
    try:
        conn = _get_conn()
        cur  = conn.cursor()
        placeholders = ",".join(["%s"] * len(sheet_names))
        cur.execute(
            f"""
            SELECT city_name, COALESCE(potential_impressions, unique_cookies, 1) AS weight
            FROM   city_reference
            WHERE  sheet_name IN ({placeholders})
            ORDER  BY weight DESC NULLS LAST
            """,
            sheet_names,
        )
        rows = cur.fetchall()
        cur.close(); conn.close()
        seen: set[str] = set()
        results = []
        for city_name, weight in rows:
            key = city_name.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            results.append({"name": city_name.strip(), "weight": float(weight or 1.0)})
        return results
    except Exception as e:
        print(f"[DB] load_city_db_sheet failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Math / formatting helpers
# ---------------------------------------------------------------------------

def pct(num: float, den: float, decimals: int = 2) -> str:
    if den == 0:
        return "0.00%"
    return f"{round((num / den) * 100, decimals):.{decimals}f}%"

def rand_float(mn: float, mx: float) -> float:
    return mn + random.random() * (mx - mn)

def rand_int(mn: int, mx: int) -> int:
    return random.randint(mn, mx)

def safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except Exception:
        pass
    s = str(val).strip().replace(",", "").replace(" ", "")
    if s.lower() in {"", "nan", "none", "<na>", "na", "null"}:
        return default
    if s.endswith("%"):
        try:
            out = float(s[:-1]) / 100.0
            return out if math.isfinite(out) else default
        except ValueError:
            return default
    try:
        out = float(s)
        return out if math.isfinite(out) else default
    except ValueError:
        return default

def safe_int(val, default: int = 0) -> int:
    try:
        out = safe_float(val, default)
        return int(out) if math.isfinite(out) else int(default)
    except (TypeError, ValueError, OverflowError):
        return int(default)

def serial_to_date(serial) -> str:
    try:
        serial = float(serial)
        utc_days = int(serial - 25569)
        import datetime as _dt
        dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + _dt.timedelta(days=utc_days)
        return dt.strftime("%d %B, %Y")
    except Exception:
        return str(serial)

def _clean_url(u: str) -> str:
    u = str(u).lower().strip()
    for prefix in ("https://", "http://", "www."):
        if u.startswith(prefix):
            u = u[len(prefix):]
    return u.rstrip("/")

def _largest_remainder(weights: list[float], total_weight: float, total_count: int) -> list[int]:
    if not weights or total_count <= 0:
        return [0] * len(weights)
    if total_weight <= 0:
        total_weight = sum(weights) or 1.0
    fractions = [(w / total_weight) * total_count for w in weights]
    integers  = [int(f) for f in fractions]
    remainders = [(f - i, idx) for idx, (f, i) in enumerate(zip(fractions, integers))]
    remainders.sort(key=lambda x: x[0], reverse=True)
    gap = total_count - sum(integers)
    for i in range(int(gap)):
        integers[remainders[i][1]] += 1
    return integers

def deduplicate_preserving_sum(values: list[int], gap: int = 1) -> list[int]:
    _n = len(values)
    if _n < 2:
        return values
    items = [[i, v] for i, v in enumerate(values)]
    items.sort(key=lambda x: x[1], reverse=True)
    used: set[int] = set()
    for k in range(_n):
        val = items[k][1]
        if val not in used and all(abs(val - u) >= gap for u in used):
            used.add(val); continue
        found = False
        for _gap in sorted([gap, 5, 3, 2, 1], reverse=True):
            if _gap > gap: continue
            for _ in range(50):
                off  = random.randint(_gap, max(_gap + 5, _n))
                sign = random.choice([-1, 1])
                cand = val + sign * off
                if cand >= 1 and cand not in used and all(abs(cand - u) >= _gap for u in used):
                    items[k][1] = cand; used.add(cand); found = True; break
            if found: break
        if not found:
            off = 1
            while True:
                for cand in [val + off, val - off]:
                    if cand >= 1 and cand not in used:
                        items[k][1] = cand; used.add(cand); found = True; break
                if found: break
                off += 1
    drift = sum(values) - sum(x[1] for x in items)
    if drift:
        items.sort(key=lambda x: x[1], reverse=True)
        for k in range(_n):
            if not drift: break
            step = 1 if drift > 0 else -1
            cand = items[k][1] + step
            if cand >= 1 and cand not in used:
                items[k][1] = cand; used.add(cand); drift -= step
        if drift:
            items[0][1] += drift
    items.sort(key=lambda x: x[0])
    return [x[1] for x in items]


# ---------------------------------------------------------------------------
# Excel styling
# ---------------------------------------------------------------------------

HEADER_BG = "00B0F0"
TOTAL_BG  = "9BC2E6"
_ALIGN_CACHE: dict[str, Alignment] = {}

def _thin_border() -> Border:
    s = Side(style="thin", color="000000")
    return Border(left=s, right=s, top=s, bottom=s)

def _align(horizontal: str) -> Alignment:
    if horizontal not in _ALIGN_CACHE:
        _ALIGN_CACHE[horizontal] = Alignment(horizontal=horizontal, vertical="center")
    return _ALIGN_CACHE[horizontal]

def _style_header(ws, row: int, num_cols: int):
    fill = PatternFill("solid", fgColor=HEADER_BG)
    font = Font(bold=True, color="000000", size=11, name="Calibri")
    for c in range(1, num_cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = fill; cell.font = font; cell.border = _thin_border()
    ws.row_dimensions[row].height = 14.50

def _style_total(ws, row: int, num_cols: int):
    fill = PatternFill("solid", fgColor=TOTAL_BG)
    font = Font(bold=True, color="000000", size=10, name="Calibri")
    for c in range(1, num_cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = fill; cell.font = font; cell.border = _thin_border()

def _auto_fit(ws):
    for col in ws.columns:
        width = 10
        for idx, cell in enumerate(col):
            if idx >= 200: break
            width = max(width, len(str(cell.value or "")))
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(width + 4, 50)

_NUMERIC_HEADERS = {
    "Impressions", "Clicks", "Reach", "Frequency",
    "Measurable Impressions", "Viewable Impressions",
    "Sum of Starts (Video)", "Sum of Complete Views (Video)",
}

def _is_numeric_like(val) -> bool:
    if val is None or isinstance(val, bool): return False
    if isinstance(val, (int, float)): return True
    s = str(val).strip().replace(",", "")
    if s.endswith("%"): s = s[:-1]
    try: float(s); return True
    except Exception: return False

def write_sheet(ws, headers: list[str], rows: list[dict],
                total_row: Optional[dict] = None,
                formulas: Optional[dict] = None,
                alignments=None):
    ws.sheet_view.showGridLines = True
    formulas   = formulas or {}
    alignments = alignments or {}
    col_map = {h: get_column_letter(i) for i, h in enumerate(headers, 1)}

    def _assign(cell, val, h_name=None, row_idx=None):
        if hasattr(val, "item"): val = val.item()
        if h_name in formulas and row_idx is not None:
            f = formulas[h_name]
            for href, let in col_map.items():
                f = f.replace(f"{{{href}}}", f"{let}{row_idx}")
            cell.value = f"={f}"
            if h_name in ("CTR", "Click Rate (CTR)", "Viewability", "VCR (Completion Rate)"):
                cell.number_format = "0.00%"
            return
        if isinstance(val, str) and val.strip().endswith("%"):
            try:
                cell.value = float(val.strip()[:-1]) / 100.0
                cell.number_format = "0.00%"
            except Exception:
                cell.value = val
        elif isinstance(val, str) and val.lstrip("-").isdigit():
            cell.value = int(val)
            if h_name in _NUMERIC_HEADERS: cell.number_format = "0"
        else:
            cell.value = val
            if h_name in _NUMERIC_HEADERS and isinstance(val, (int, float)):
                cell.number_format = "0"

    # Header row
    for c_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c_idx, value=h)
        cell.alignment = _align("center")
    _style_header(ws, 1, len(headers))

    # Data rows
    for r_idx, row in enumerate(rows, 2):
        for c_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=r_idx, column=c_idx)
            raw  = row.get(h, "")
            _assign(cell, raw, h_name=h, row_idx=r_idx)
            cell.font   = Font(size=10, name="Calibri")
            cell.border = _thin_border()
            if c_idx == 1:
                cell.alignment = _align("left")
            elif h in formulas or h in _NUMERIC_HEADERS or _is_numeric_like(raw):
                cell.alignment = _align("right")
            elif isinstance(alignments, dict) and h in alignments:
                cell.alignment = _align(alignments[h])
            else:
                cell.alignment = _align("center")

    # Total row
    if total_row:
        t = 2 + len(rows)
        for c_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=t, column=c_idx)
            val  = total_row.get(h, "")
            if h in formulas:
                f = formulas[h]
                for href, let in col_map.items():
                    f = f.replace(f"{{{href}}}", f"{let}{t}")
                cell.value = f"={f}"; cell.number_format = "0.00%"
            elif h in _NUMERIC_HEADERS:
                let = col_map[h]
                cell.value = f"=SUM({let}2:{let}{t-1})"
                cell.number_format = "#,##0"
            else:
                _assign(cell, val)
            if c_idx == 1:
                cell.alignment = _align("left")
            else:
                cell.alignment = _align("right")
        _style_total(ws, t, len(headers))

    _auto_fit(ws)
    try:
        ws.ignored_errors.append(IgnoredError(
            sqref="A1:ZZ5000",
            numberStoredAsText=True, evalError=True,
            emptyCellReference=True, calculatedColumn=True,
        ))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Sheet builders (ported directly from App.py)
# ---------------------------------------------------------------------------

def build_sheet1_reach(total_imp: int, total_clk: int) -> list[dict]:
    ctr   = pct(total_clk, total_imp)
    freq  = 3
    reach = int(total_imp / freq) + random.randint(200, 300)
    return [{"Impressions": total_imp, "Clicks": total_clk,
             "Click Rate (CTR)": ctr, "Reach": reach, "Frequency": freq}]


def build_sheet2_date(df: pd.DataFrame, total_imp: int, total_clk: int,
                       ctr_reach: str, is_banner: bool = False):
    rows = []
    sum_imp = sum_clk = sum_view = sum_meas = sum_starts = sum_comp = 0
    vcr_weighted = vcr_imp_total = 0

    for _, r in df.iterrows():
        imp = safe_int(r.get("Impressions", 0))
        clk = safe_int(r.get("Clicks", 0))
        date_val = r.get("Date", "")
        # pandas Timestamp / Python datetime → format directly
        if hasattr(date_val, "strftime"):
            date_str = date_val.strftime("%d %B, %Y")
        else:
            try:
                float(date_val)          # Excel serial number
                date_str = serial_to_date(date_val)
            except (ValueError, TypeError):
                date_str = str(date_val)

        sum_imp += imp; sum_clk += clk

        if is_banner:
            meas = round(imp * random.uniform(0.90, 0.96))
            view = round(meas * random.uniform(0.75, 0.85))
            sum_view += view; sum_meas += meas
            rows.append({"Date": date_str, "Impressions": imp, "Clicks": clk,
                         "Click Rate (CTR)": pct(clk, imp),
                         "Viewable Impressions": view,
                         "Measurable Impressions": meas,
                         "Viewability": pct(view, meas)})
        else:
            view   = safe_int(r.get("Viewable Impressions", 0))
            meas   = safe_int(r.get("Measurable Impressions", 0))
            starts = safe_int(r.get("Start views", 0))
            comps  = safe_int(r.get("Complete Views", 0))
            vcr_raw = safe_float(r.get("Video Completion Rate (VCR)", 0))
            sum_view += view; sum_meas += meas
            sum_starts += starts; sum_comp += comps
            vcr_weighted += vcr_raw * imp; vcr_imp_total += imp
            vcr_pct = f"{round(vcr_raw * 100)}%" if vcr_raw > 0 else "0%"
            rows.append({"Date": date_str, "Impressions": imp, "Clicks": clk,
                         "Click Rate (CTR)": pct(clk, imp),
                         "Viewable Impressions": view,
                         "Measurable Impressions": meas,
                         "Viewability": pct(view, meas),
                         "Sum of Starts (Video)": starts,
                         "Sum of Complete Views (Video)": comps,
                         "VCR (Completion Rate)": vcr_pct})

    if is_banner:
        total = {"Date": "Grand Total", "Impressions": sum_imp, "Clicks": sum_clk,
                 "Click Rate (CTR)": ctr_reach,
                 "Viewable Impressions": sum_view,
                 "Measurable Impressions": sum_meas,
                 "Viewability": pct(sum_view, sum_meas)}
    else:
        avg_vcr = f"{round((vcr_weighted / vcr_imp_total) * 100)}%" if vcr_imp_total > 0 else "0%"
        total = {"Date": "Grand Total", "Impressions": sum_imp, "Clicks": sum_clk,
                 "Click Rate (CTR)": ctr_reach,
                 "Viewable Impressions": sum_view,
                 "Measurable Impressions": sum_meas,
                 "Viewability": pct(sum_view, sum_meas),
                 "Sum of Starts (Video)": sum_starts,
                 "Sum of Complete Views (Video)": sum_comp,
                 "VCR (Completion Rate)": avg_vcr}
    return rows, total


def build_sheet3_timeofday(total_imp: int, total_clk: int, ctr_reach: str):
    hour_weights = {
        0:0.5,1:0.4,2:0.3,3:0.3,4:0.4,5:0.7,6:1.2,7:1.5,
        8:2.0,9:2.5,10:2.3,11:2.4,12:2.2,13:1.8,14:1.6,15:1.7,
        16:1.9,17:2.6,18:2.8,19:2.5,20:2.0,21:1.6,22:1.2,23:0.8
    }
    noisy = [hour_weights[h] * (0.85 + random.random() * 0.30) for h in range(24)]
    total_w = sum(noisy)
    hourly_imp = [int((w / total_w) * total_imp) for w in noisy]
    diff = total_imp - sum(hourly_imp)
    for _ in range(abs(diff)):
        hourly_imp[random.randint(0, 23)] += 1 if diff > 0 else -1
    hourly_imp = deduplicate_preserving_sum(hourly_imp, gap=1)

    hourly_clk = []
    for imp in hourly_imp:
        if imp >= 180:
            c_min = math.ceil(imp * 0.0035)
            c_max = math.floor(imp * 0.0056)
            hourly_clk.append(random.randint(c_min, max(c_min, c_max)))
        else:
            hourly_clk.append(0)

    current  = sum(hourly_clk)
    diff_clk = total_clk - current
    eligible = [i for i, imp in enumerate(hourly_imp) if imp >= 180]
    iterations = 0
    while diff_clk != 0 and eligible and iterations < 5000:
        iterations += 1
        idx = random.choice(eligible)
        imp = hourly_imp[idx]; clk = hourly_clk[idx]
        if diff_clk > 0:
            if (clk + 1) / imp <= 0.0056:
                hourly_clk[idx] += 1; diff_clk -= 1
        elif diff_clk < 0:
            if clk > 1 and (clk - 1) / imp >= 0.0035:
                hourly_clk[idx] -= 1; diff_clk += 1

    rows = [{"Time of Day": h, "Impressions": hourly_imp[h],
              "Clicks": hourly_clk[h], "Click Rate (CTR)": pct(hourly_clk[h], hourly_imp[h])}
             for h in range(24)]
    total = {"Time of Day": "Grand Total", "Impressions": total_imp,
             "Clicks": total_clk, "Click Rate (CTR)": ctr_reach}
    return rows, total


def build_sheet4_age(total_imp: int, total_clk: int, ctr_reach: str):
    pct_1824 = rand_float(0.20, 0.25)
    pct_4554 = rand_float(0.09, 0.12)
    remaining = max(0.60, min(0.74, 1 - pct_1824 - pct_4554))
    split = rand_float(0.45, 0.55)
    pct_2534 = remaining * split
    pct_3544 = remaining - pct_2534

    imp_1824 = round(total_imp * pct_1824)
    imp_4554 = round(total_imp * pct_4554)
    rem_imp  = total_imp - imp_1824 - imp_4554
    imp_2534 = round(rem_imp * split)
    imp_3544 = rem_imp - imp_2534
    imp_2534 += total_imp - (imp_1824 + imp_2534 + imp_3544 + imp_4554)

    groups = [{"age": "18-24", "imp": imp_1824}, {"age": "25-34", "imp": imp_2534},
              {"age": "35-44", "imp": imp_3544}, {"age": "45-54", "imp": imp_4554}]
    clicks = [round(g["imp"] * rand_float(0.0035, 0.0056)) if g["imp"] >= 180 else 0 for g in groups]
    c_sum  = sum(clicks)
    if c_sum > 0:
        clicks = [round(c * total_clk / c_sum) if groups[i]["imp"] >= 180 else 0 for i, c in enumerate(clicks)]
    drift = total_clk - sum(clicks)
    clicks[clicks.index(max(clicks))] += drift

    rows = [{"Age": g["age"], "Impressions": g["imp"], "Clicks": clicks[i],
              "Click Rate (CTR)": pct(clicks[i], g["imp"])} for i, g in enumerate(groups)]
    total = {"Age": "Grand Total", "Impressions": total_imp, "Clicks": total_clk, "Click Rate (CTR)": ctr_reach}
    return rows, total


def build_sheet5_gender(total_imp: int, total_clk: int, ctr_reach: str):
    female_pct = rand_float(0.30, 0.40)
    imp_female = round(total_imp * female_pct)
    imp_male   = total_imp - imp_female
    male_pct   = imp_male / total_imp
    if male_pct < 0.58:
        imp_male   = round(total_imp * rand_float(0.58, 0.61))
        imp_female = total_imp - imp_male
    elif male_pct > 0.65:
        imp_male   = round(total_imp * rand_float(0.62, 0.65))
        imp_female = total_imp - imp_male
    imp_male += total_imp - (imp_male + imp_female)

    groups = [{"gender": "Male", "imp": imp_male}, {"gender": "Female", "imp": imp_female}]
    clicks = [round(g["imp"] * rand_float(0.0035, 0.0056)) if g["imp"] >= 180 else 0 for g in groups]
    g_sum  = sum(clicks)
    if g_sum > 0:
        clicks = [round(c * total_clk / g_sum) if groups[i]["imp"] >= 180 else 0 for i, c in enumerate(clicks)]
    drift = total_clk - sum(clicks)
    clicks[clicks.index(max(clicks))] += drift

    rows = [{"Gender": g["gender"], "Impressions": g["imp"], "Clicks": clicks[i],
              "Click Rate (CTR)": pct(clicks[i], g["imp"])} for i, g in enumerate(groups)]
    total = {"Gender": "Grand Total", "Impressions": total_imp, "Clicks": total_clk, "Click Rate (CTR)": ctr_reach}
    return rows, total


def build_sheet6_device(total_imp: int, total_clk: int, ctr_reach: str):
    tablet_pct  = rand_float(0.07, 0.10)
    desktop_shr = rand_float(0.45, 0.55)
    rem         = 1 - tablet_pct
    imp_tablet  = round(total_imp * tablet_pct)
    imp_desktop = round(total_imp * rem * desktop_shr)
    imp_mobile  = total_imp - imp_tablet - imp_desktop
    imp_mobile += total_imp - (imp_desktop + imp_mobile + imp_tablet)

    groups = [{"device": "Desktop",     "imp": imp_desktop},
              {"device": "Smart Phone", "imp": imp_mobile},
              {"device": "Tablet",      "imp": imp_tablet}]
    clicks = [max(0, int(g["imp"] * rand_float(0.0035, 0.0056))) if g["imp"] >= 180 else 0 for g in groups]
    d_sum  = sum(clicks)
    if d_sum > 0:
        clicks = [int(c * total_clk / d_sum) if groups[i]["imp"] >= 180 else 0 for i, c in enumerate(clicks)]
    drift = total_clk - sum(clicks)
    clicks[clicks.index(max(clicks))] += drift

    rows = [{"Device Type": g["device"], "Impressions": g["imp"], "Clicks": clicks[i],
              "Click Rate (CTR)": pct(clicks[i], g["imp"])} for i, g in enumerate(groups)]
    total = {"Device Type": "Grand Total", "Impressions": total_imp, "Clicks": total_clk, "Click Rate (CTR)": ctr_reach}
    return rows, total


def build_sheet7_exchange(total_imp: int, total_clk: int, ctr_reach: str):
    tier1_other = ["BidSwitch","Index Exchange","Magnite DV+","PubMatic"]
    tier2 = ["Criteo Commerce Grid","Equativ","InMobi","Media.net","Nexxen (fka Unruly)","OpenX","Sovrn"]
    tier3 = ["Microsoft Monetize","Epsilon Core Private Exchange","Yieldmo","TripleLift",
             "Kargo","Improve Digital","TeadsTv","GumGum","Adform"]

    ex_t1 = int(total_imp * rand_float(0.80, 0.85))
    ex_t2 = int(total_imp * rand_float(0.08, 0.13))
    ex_t3 = total_imp - ex_t1 - ex_t2
    google = int(ex_t1 * rand_float(0.35, 0.45))
    t1_other = ex_t1 - google

    def split_across(names, total):
        remaining = total; result = []
        for i, name in enumerate(names):
            if i == len(names) - 1:
                imp = remaining
            else:
                imp = max(1, rand_int(1, int((remaining - (len(names)-1-i)) * 0.6)))
            remaining -= imp
            result.append({"name": name, "imp": imp})
        return result

    exchanges = ([{"name": "Google Ad Manager", "imp": google}]
                 + split_across(tier1_other, t1_other)
                 + split_across(tier2, ex_t2)
                 + split_across(tier3, ex_t3))
    drift = total_imp - sum(e["imp"] for e in exchanges)
    exchanges[0]["imp"] += drift

    clicks = [round(e["imp"] * rand_float(0.0035, 0.0056)) if e["imp"] >= 180 else 0 for e in exchanges]
    e_sum  = sum(clicks)
    if e_sum > 0:
        clicks = [round(c * total_clk / e_sum) if exchanges[i]["imp"] >= 180 else 0 for i, c in enumerate(clicks)]
    e_drift = total_clk - sum(clicks)
    max_idx = max(range(len(exchanges)), key=lambda i: exchanges[i]["imp"])
    clicks[max_idx] += e_drift

    rows = sorted([{"Exchange": e["name"], "Impressions": e["imp"], "Clicks": clicks[i],
                    "Click Rate (CTR)": pct(clicks[i], e["imp"])} for i, e in enumerate(exchanges)],
                  key=lambda x: x["Exchange"])
    total = {"Exchange": "Grand Total", "Impressions": total_imp, "Clicks": total_clk, "Click Rate (CTR)": ctr_reach}
    return rows, total


def _find_li_col(frame: pd.DataFrame) -> Optional[str]:
    """Return the 'Line Item' column name from a DataFrame, or None."""
    for col in frame.columns:
        if "line item" in col.strip().lower():
            return col
    return None


def _li_tokens(val) -> set:
    """
    Extract comparable tokens from a Line Item string.
    Strips leading 'LI12345|' prefix and normalises to lowercase words.
    e.g. 'LI09075|Zee5 - Indian - 15 Sec' → {'zee5','indian','15','sec'}
    Safe against None / float NaN values.
    """
    if val is None:
        return set()
    try:
        import math
        if isinstance(val, float) and math.isnan(val):
            return set()
    except Exception:
        pass
    val = str(val).strip()
    if not val or val.lower() in {"nan", "none", ""}:
        return set()
    val = re.sub(r'^[A-Za-z]{2}\d+\|', '', val).strip().lower()
    return set(re.split(r'[\s\-|,_]+', val)) - {'', '-'}


def build_sheet9_creative(df: pd.DataFrame, total_imp: int, total_clk: int, ctr_reach: str,
                           df2: Optional[pd.DataFrame] = None, li_hint: str = ""):
    """
    Creative sheet — group by Creative column.
    Filters the creative source to only Line Items present in df (the split/main file)
    so that a Vietnamese report shows only Vietnamese creatives, etc.
    """
    _CREATIVE_KEYS = {"creative", "ad name", "ad content", "ad"}

    def _find_creative_col(frame: pd.DataFrame) -> Optional[str]:
        for col in frame.columns:
            if col.strip().lower() in _CREATIVE_KEYS:
                return col
        return None

    # Prefer main df; fall back to df2
    source = df
    creative_col = _find_creative_col(df)
    if creative_col is None and df2 is not None:
        creative_col = _find_creative_col(df2)
        if creative_col is not None:
            source = df2

    if creative_col is None:
        return [], {"Creative": "Grand Total", "Impressions": total_imp,
                    "Clicks": total_clk, "Click Rate (CTR)": ctr_reach}

    # ── Filter source to only the Line Items present in df ──────────────
    # This ensures e.g. a Vietnamese split file only gets Vietnamese creatives.
    if source is not df:
        li_col_df  = _find_li_col(df)
        li_col_src = _find_li_col(source)
        _filtered  = False   # track whether we applied a filter

        if li_col_df and li_col_src:
            # Normalise Line Item values from the split file
            df_li_raw  = (df[li_col_df].dropna()
                           .apply(lambda v: str(v).strip())
                           .replace({"nan": None, "None": None, "": None})
                           .dropna().unique())
            df_li_norm = {v.lower() for v in df_li_raw if v}
            df_li_tok  = [t for v in df_li_raw if v for t in [_li_tokens(v)] if t]

            src_li = source[li_col_src].fillna("").astype(str).str.strip()

            # 1. Exact match (case-insensitive)
            exact_mask = src_li.str.lower().isin(df_li_norm)

            # 2. Strip 'LI12345|' prefix from source side
            src_li_clean = src_li.str.replace(r'^[A-Za-z]{2}\d+\|', '', regex=True).str.strip()
            prefix_mask  = src_li_clean.str.lower().isin(df_li_norm)

            # 3. Token overlap ≥60%
            def _token_match(val) -> bool:
                toks = _li_tokens(val)
                if not toks:
                    return False
                for ref in df_li_tok:
                    if ref and len(toks & ref) / max(len(ref), 1) >= 0.6:
                        return True
                return False
            token_mask = src_li.apply(_token_match)

            # Waterfall: strictest match wins
            if exact_mask.any():
                source = source[exact_mask].copy(); _filtered = True
            elif prefix_mask.any():
                source = source[prefix_mask].copy(); _filtered = True
            elif token_mask.any():
                source = source[token_mask].copy(); _filtered = True

        if not _filtered and li_hint and li_col_src:
            # df has no Line Item column (single-LI split file).
            # Use filename stem as hint and pick df2 rows whose Line Item
            # has the MOST token overlap with the hint (argmax, not threshold).
            # "Cantonese Banner" hint → Cantonese LI wins over Japanese LI
            # even though both share "Banner" and campaign ID.
            hint_toks = _li_tokens(li_hint)
            if hint_toks:
                counts = source[li_col_src].apply(
                    lambda v: len(hint_toks & _li_tokens(v))
                )
                max_cnt = counts.max()
                if max_cnt > 0:
                    source = source[counts == max_cnt].copy(); _filtered = True

        if not _filtered and li_hint and creative_col:
            # Last resort: no LI column in df2 either.
            # Filter by creative NAME — pick rows with the most token overlap
            # with li_hint (e.g. creative "Cantonese_Banner_300x250" scores
            # higher than "Japanese_Banner_300x250" for hint "Cantonese Banner").
            hint_toks = _li_tokens(li_hint)
            if hint_toks:
                counts = source[creative_col].apply(
                    lambda v: len(hint_toks & _li_tokens(str(v)))
                )
                max_cnt = counts.max()
                if max_cnt > 0:
                    source = source[counts == max_cnt].copy()

    # Group by creative, sum impressions and clicks
    df_copy = source.copy()
    df_copy["_imp"] = df_copy.get("Impressions", pd.Series([0] * len(df_copy))).apply(safe_float)
    df_copy["_clk"] = df_copy.get("Clicks",      pd.Series([0] * len(df_copy))).apply(safe_float)
    df_copy["_creative"] = df_copy[creative_col].astype(str).str.strip()

    grouped = (df_copy.groupby("_creative", sort=True)
               .agg(raw_imp=("_imp", "sum"), raw_clk=("_clk", "sum"))
               .reset_index())
    grouped = grouped[grouped["_creative"].str.lower() != "nan"]
    grouped = grouped.sort_values("_creative")

    if grouped.empty:
        return [], {"Creative": "Grand Total", "Impressions": total_imp,
                    "Clicks": total_clk, "Click Rate (CTR)": ctr_reach}

    # Distribute total_imp proportionally using largest-remainder
    weights = list(grouped["raw_imp"].values)
    total_w = sum(weights) or 1.0
    cr_imps = _largest_remainder(weights, total_w, total_imp)

    # Distribute total_clk proportionally
    clk_weights = list(grouped["raw_clk"].values)
    clk_w = sum(clk_weights) or 1.0
    cr_clks = _largest_remainder(clk_weights, clk_w, total_clk)

    # Correct any drift
    imp_drift = total_imp - sum(cr_imps)
    if imp_drift:
        cr_imps[cr_imps.index(max(cr_imps))] += imp_drift
    clk_drift = total_clk - sum(cr_clks)
    if clk_drift:
        cr_clks[cr_clks.index(max(cr_clks))] += clk_drift

    rows = [{"Creative": grouped.iloc[i]["_creative"],
             "Impressions": cr_imps[i],
             "Clicks": cr_clks[i],
             "Click Rate (CTR)": pct(cr_clks[i], cr_imps[i])}
            for i in range(len(grouped))]
    total = {"Creative": "Grand Total", "Impressions": total_imp,
             "Clicks": total_clk, "Click Rate (CTR)": ctr_reach}
    return rows, total


def build_sheet8_city(total_imp: int, total_clk: int, ctr_reach: str,
                       city_sheet_names: list[str]):
    """City sheet — distribute across cities from city_reference DB."""
    db_cities = load_city_db_sheet(city_sheet_names)
    if not db_cities:
        # Fallback cities
        db_cities = [{"name": c, "weight": 1.0} for c in
                     ["Sydney","Melbourne","Brisbane","Perth","Adelaide","Canberra"]]

    # Cap at 60, min 6
    db_cities.sort(key=lambda x: x["weight"], reverse=True)
    if len(db_cities) > 60:
        db_cities = db_cities[:60]

    db_cities.sort(key=lambda x: x["name"].lower())
    weights    = [max(c["weight"], 1.0) for c in db_cities]
    total_w    = sum(weights)
    city_imps  = _largest_remainder(weights, total_w, total_imp)
    city_imps  = deduplicate_preserving_sum(city_imps, gap=1)

    city_clks = [round(imp * rand_float(0.0035, 0.0056)) if imp >= 180 else 0
                 for imp in city_imps]
    c_sum = sum(city_clks) or 1
    city_clks = [round(c * total_clk / c_sum) if city_imps[i] >= 180 else 0
                 for i, c in enumerate(city_clks)]
    drift = total_clk - sum(city_clks)
    if drift:
        city_clks[max(range(len(city_imps)), key=lambda i: city_imps[i])] += drift

    rows = [{"City": db_cities[i]["name"], "Impressions": city_imps[i],
              "Clicks": city_clks[i], "Click Rate (CTR)": pct(city_clks[i], city_imps[i])}
             for i in range(len(db_cities))]
    total = {"City": "Grand Total", "Impressions": total_imp, "Clicks": total_clk,
             "Click Rate (CTR)": pct(total_clk, total_imp)}
    return rows, total


def build_sheet10_apps(total_imp: int, total_clk: int,
                        language_sheet_names: list[str],
                        user_urls_text: str):
    """App/URL sheet — combine DB URLs + user URLs, distribute impressions."""
    _JUNK = {"nan", "none", "", "app/url", "app", "url", "site", "domain"}

    # User URLs
    user_apps = [_clean_url(u) for u in user_urls_text.splitlines()
                 if _clean_url(u) not in _JUNK]
    user_set  = set(user_apps)

    # DB URLs from selected language sheets
    db_urls = [u for u in get_urls_from_sheets(language_sheet_names)
               if u not in user_set and u not in _JUNK]
    random.shuffle(db_urls)

    # Target row count
    if total_imp < 50_000:
        target = random.randint(40, 50);   top_lo, top_hi = 10_000, 12_000
    elif total_imp < 70_000:
        target = random.randint(50, 60);   top_lo, top_hi = 12_000, 15_000
    elif total_imp < 100_000:
        target = random.randint(60, 70);   top_lo, top_hi = 15_000, 20_000
    elif total_imp < 500_000:
        target = random.randint(110, 120); top_lo, top_hi = 18_000, 35_000
    elif total_imp < 1_000_000:
        target = random.randint(110, 120); top_lo, top_hi = 40_000, 50_000
    else:
        target = random.randint(110, 120); top_lo, top_hi = 70_000, 80_000

    # Place user URLs first, fill with DB URLs
    n_user = len(user_apps)
    filler = db_urls[:max(0, target - n_user)]
    all_apps = user_apps + filler
    if not all_apps:
        all_apps = ["facebook.com", "youtube.com", "instagram.com"]
    n = len(all_apps)

    top_hi = min(top_hi, int(total_imp * 0.48)) if total_imp > 0 else top_hi
    top_lo = max(1, min(top_lo, top_hi - 500))
    target_top = random.randint(top_lo, top_hi)

    other_weights: list[float] = []
    for i in range(1, n):
        if   i < 8:  w = random.uniform(0.55, 0.90)
        elif i < 20: w = random.uniform(0.08, 0.25)
        elif i < 85: w = random.uniform(0.003, 0.04)
        else:        w = random.uniform(0.0005, 0.006)
        other_weights.append(w)

    remainder_imp = max(0, total_imp - target_top)
    sum_oth = sum(other_weights) or 1.0
    if sum_oth > 0 and remainder_imp > 0:
        scale = remainder_imp / sum_oth
        other_weights = [w * scale for w in other_weights]

    imp_weights = [float(target_top)] + other_weights
    w_total     = sum(imp_weights)
    app_imps    = _largest_remainder(imp_weights, w_total, total_imp)
    app_imps    = deduplicate_preserving_sum(app_imps, gap=7)

    raw_clks = [imp * rand_float(0.0025, 0.0085) if imp >= 180 else 0.0 for imp in app_imps]
    # User URL positions get tighter CTR
    for i in range(min(n_user, n)):
        if app_imps[i] >= 180:
            raw_clks[i] = app_imps[i] * rand_float(0.0045, 0.0052)

    w_clk = sum(raw_clks) or float(n)
    app_clks = _largest_remainder(raw_clks, w_clk, total_clk)

    drift = total_clk - sum(app_clks)
    if drift > 0:
        app_clks[0] += drift
    elif drift < 0:
        for i in range(abs(drift)):
            idx = max(range(n), key=lambda j: app_clks[j])
            if app_clks[idx] > 1:
                app_clks[idx] -= 1

    rows = [{"App/URL": all_apps[i], "Impressions": app_imps[i],
              "Clicks": app_clks[i], "Click Rate (CTR)": pct(app_clks[i], app_imps[i])}
             for i in range(n)]
    rows.sort(key=lambda x: x["Impressions"], reverse=True)

    total = {"App/URL": "Grand Total", "Impressions": total_imp,
             "Clicks": total_clk, "Click Rate (CTR)": pct(total_clk, total_imp)}
    return rows, total


# ---------------------------------------------------------------------------
# Banner format parser
# ---------------------------------------------------------------------------

def _parse_banner_format(file_bytes: bytes):
    """
    Detect and parse the special banner daily-report Excel format:

      Row 0 : [start_date,    line_item_name, NaN, 'Daily']
      ...
      Row N : ['Daily Report', total_imp,     total_clk, ctr_pct]   ← totals
      Row N+1: ['Date',        'Impressions', 'Clicks',  'CTR']     ← headers
      Row N+2+: actual daily rows

    Returns (date_df, total_imp, total_clk) if detected, else None.
    """
    try:
        raw = pd.read_excel(io.BytesIO(file_bytes), header=None)
    except Exception:
        return None

    total_imp = total_clk = 0
    date_header_idx = None

    for i, row in raw.iterrows():
        v0 = str(row.iloc[0]).strip().lower() if row.iloc[0] is not None else ""
        if v0 == "daily report":
            total_imp = safe_int(row.iloc[1]) if len(row) > 1 else 0
            total_clk = safe_int(row.iloc[2]) if len(row) > 2 else 0
        if v0 == "date":
            date_header_idx = i
            break

    # Both "Daily Report" row AND "Date" header row must exist for banner format.
    # Standard files have "Date" in row 0 as a normal header — those should NOT
    # be treated as banner format (they'd lose video columns like VCR, Start views).
    if date_header_idx is None or total_imp == 0:
        return None

    # Derive totals from data rows if "Daily Report" row was missing
    date_rows = []
    for i in range(int(date_header_idx) + 1, len(raw)):
        row      = raw.iloc[i]
        date_val = row.iloc[0]
        imp_val  = row.iloc[1] if len(row) > 1 else 0
        clk_val  = row.iloc[2] if len(row) > 2 else 0
        if date_val is None or str(date_val).strip().lower() in ("", "nan", "none"):
            continue
        date_rows.append({
            "Date":        str(date_val).strip(),
            "Impressions": safe_int(imp_val),
            "Clicks":      safe_int(clk_val),
        })

    if not date_rows:
        return None

    date_df = pd.DataFrame(date_rows)

    # If "Daily Report" row was absent, sum from parsed rows
    if total_imp == 0:
        total_imp = int(date_df["Impressions"].sum())
    if total_clk == 0:
        total_clk = int(date_df["Clicks"].sum())

    return date_df, total_imp, total_clk


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_report(
    campaign_file_bytes: bytes,
    campaign_filename: str,
    language_sheet_names: list[str],
    city_sheet_names: list[str],
    user_urls_text: str = "",
    mode: str = "video",
    creative_file_bytes: Optional[bytes] = None,
) -> bytes:
    """
    Generate a multi-sheet Excel report and return it as bytes.

    Parameters
    ----------
    campaign_file_bytes : raw bytes of the split campaign Excel
    campaign_filename   : original filename (used for ext detection)
    language_sheet_names: selected sheets from app_url_reference
    city_sheet_names    : selected sheets from city_reference
    user_urls_text      : newline-separated URLs from textarea
    mode                : "video" or "banner"
    """
    is_banner = (mode.lower() == "banner")
    ext = campaign_filename.rsplit(".", 1)[-1].lower()

    # ── Try banner daily-report format first ──────────────────────────────
    # Files like "Japanese Banner.xlsx" have a special layout:
    #   Row N   : "Daily Report" | total_imp | total_clk | ctr
    #   Row N+1 : "Date" | "Impressions" | "Clicks" | "CTR"
    #   Row N+2+: actual daily rows
    # Normal pd.read_excel() misreads these (treats row 0 as header).
    banner_parsed = None
    if ext not in ("csv",):
        banner_parsed = _parse_banner_format(campaign_file_bytes)

    if banner_parsed is not None:
        # Banner format: use parsed date rows + totals from "Daily Report" row
        df_date, total_imp, total_clk = banner_parsed
        # Synthetic df1 for creative/city matching (line item = filename stem)
        li_stem = campaign_filename.rsplit(".", 1)[0]
        df1 = pd.DataFrame({
            "Line Item Name": [li_stem],
            "Impressions":    [total_imp],
            "Clicks":         [total_clk],
        })
        is_banner = True   # always treat parsed banner files as banner mode
    else:
        # ── Standard format ───────────────────────────────────────────────
        buf = io.BytesIO(campaign_file_bytes)
        if ext == "csv":
            df1 = pd.read_csv(buf)
        else:
            df1 = pd.read_excel(buf)

        if df1.empty:
            raise ValueError("Campaign file contains no data.")

        total_imp = int(df1.get("Impressions", pd.Series([0])).apply(safe_float).sum())
        total_clk = int(df1.get("Clicks",      pd.Series([0])).apply(safe_float).sum())

        # Fallback synthetic totals if file has no standard columns
        if total_imp == 0:
            total_imp = random.randint(150_000, 300_000)
        if total_clk == 0:
            total_clk = round(total_imp * rand_float(0.0040, 0.0055))

        # Sheet 2 — use Date column if present, else synthetic 30-day spread
        if "Date" not in df1.columns:
            import datetime as _dt
            base = _dt.date.today() - _dt.timedelta(days=30)
            df_date = pd.DataFrame({
                "Date": [(base + _dt.timedelta(days=i)).strftime("%d %B, %Y") for i in range(30)],
                "Impressions": _largest_remainder([1.0] * 30, 30.0, total_imp),
                "Clicks":      _largest_remainder([1.0] * 30, 30.0, total_clk),
            })
        else:
            df_date = df1

    ctr_reach = pct(total_clk, total_imp)

    s1            = build_sheet1_reach(total_imp, total_clk)
    s2, s2t       = build_sheet2_date(df_date, total_imp, total_clk, ctr_reach, is_banner)
    s3, s3t       = build_sheet3_timeofday(total_imp, total_clk, ctr_reach)
    s4, s4t       = build_sheet4_age(total_imp, total_clk, ctr_reach)
    s5, s5t       = build_sheet5_gender(total_imp, total_clk, ctr_reach)
    s6, s6t       = build_sheet6_device(total_imp, total_clk, ctr_reach)
    s7, s7t       = build_sheet7_exchange(total_imp, total_clk, ctr_reach)
    # Load optional second file (campaign detail / creative data)
    df2: Optional[pd.DataFrame] = None
    if creative_file_bytes:
        try:
            buf2 = io.BytesIO(creative_file_bytes)
            ext2 = campaign_filename.rsplit(".", 1)[-1].lower()
            df2 = pd.read_csv(buf2) if ext2 == "csv" else pd.read_excel(buf2)
        except Exception as e:
            print(f"[report] creative_file_bytes load failed: {e}")

    # Use filename stem as line-item hint for creative filtering
    # (when the split file has no Line Item column, we fall back to this)
    li_hint = campaign_filename.rsplit(".", 1)[0] if "." in campaign_filename else campaign_filename
    s9, s9t       = build_sheet9_creative(df1, total_imp, total_clk, ctr_reach, df2, li_hint=li_hint)
    s8, s8t       = build_sheet8_city(total_imp, total_clk, ctr_reach, city_sheet_names)
    s10, s10t     = build_sheet10_apps(total_imp, total_clk, language_sheet_names, user_urls_text)

    # Build workbook
    wb  = Workbook()
    f_ctr = {"Click Rate (CTR)": "{Clicks}/{Impressions}"}

    # REACH
    ws1 = wb.active; ws1.title = "REACH"
    write_sheet(ws1, ["Impressions","Clicks","Click Rate (CTR)","Reach","Frequency"],
                s1, formulas={"Click Rate (CTR)": "{Clicks}/{Impressions}"})

    # DATE
    ws2 = wb.create_sheet("DATE")
    if is_banner:
        h2 = ["Date","Impressions","Clicks","Click Rate (CTR)",
              "Viewable Impressions","Measurable Impressions","Viewability"]
        f2 = {"Click Rate (CTR)": "{Clicks}/{Impressions}",
              "Viewability": "{Viewable Impressions}/{Measurable Impressions}"}
    else:
        h2 = ["Date","Impressions","Clicks","Click Rate (CTR)","Viewable Impressions",
              "Measurable Impressions","Viewability","Sum of Starts (Video)",
              "Sum of Complete Views (Video)","VCR (Completion Rate)"]
        f2 = {"Click Rate (CTR)": "{Clicks}/{Impressions}",
              "Viewability": "{Viewable Impressions}/{Measurable Impressions}",
              "VCR (Completion Rate)": "{Sum of Complete Views (Video)}/{Sum of Starts (Video)}"}
    write_sheet(ws2, h2, s2, s2t, formulas=f2)

    # APP URL
    ws10 = wb.create_sheet("APP URL")
    write_sheet(ws10, ["App/URL","Impressions","Clicks","Click Rate (CTR)"],
                s10, s10t, formulas=f_ctr)

    # TIME OF DAY
    ws3 = wb.create_sheet("TIME OF DAY")
    write_sheet(ws3, ["Time of Day","Impressions","Clicks","Click Rate (CTR)"],
                s3, s3t, formulas=f_ctr)

    # EXCHANGE
    ws7 = wb.create_sheet("EXCHANGE")
    write_sheet(ws7, ["Exchange","Impressions","Clicks","Click Rate (CTR)"],
                s7, s7t, formulas=f_ctr)

    # DEVICE
    ws6 = wb.create_sheet("DEVICE")
    write_sheet(ws6, ["Device Type","Impressions","Clicks","Click Rate (CTR)"],
                s6, s6t, formulas=f_ctr)

    # CREATIVE
    ws9 = wb.create_sheet("CREATIVE")
    write_sheet(ws9, ["Creative","Impressions","Clicks","Click Rate (CTR)"],
                s9, s9t if s9 else None, formulas=f_ctr)

    # CITY
    ws8 = wb.create_sheet("CITY")
    write_sheet(ws8, ["City","Impressions","Clicks","Click Rate (CTR)"],
                s8, s8t, formulas=f_ctr)

    # AGE
    ws4 = wb.create_sheet("AGE")
    write_sheet(ws4, ["Age","Impressions","Clicks","Click Rate (CTR)"],
                s4, s4t, formulas=f_ctr)

    # GENDER
    ws5 = wb.create_sheet("GENDER")
    write_sheet(ws5, ["Gender","Impressions","Clicks","Click Rate (CTR)"],
                s5, s5t, formulas=f_ctr)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.read()
