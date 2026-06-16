"""
Unit tests for image_utils creative-matching logic.
Run with: pytest Backend_Screenshot/tests/ -v
"""
import pytest
from services.image_utils import (
    calculate_aspect_ratio_score,
    calculate_orientation_score,
    calculate_size_score,
    find_best_match,
)


# ── Aspect ratio scoring ───────────────────────────────────────────────────────

def test_aspect_ratio_exact_match():
    assert calculate_aspect_ratio_score(1.0, 1.0) == 1.0

def test_aspect_ratio_within_5_percent():
    assert calculate_aspect_ratio_score(1.04, 1.0) >= 0.99

def test_aspect_ratio_within_10_percent():
    score = calculate_aspect_ratio_score(1.09, 1.0)
    assert 0.80 <= score <= 0.90

def test_aspect_ratio_incompatible():
    assert calculate_aspect_ratio_score(4.0, 1.0) == 0.0

def test_aspect_ratio_zero_slot():
    assert calculate_aspect_ratio_score(1.0, 0) == 0.0


# ── Orientation scoring ───────────────────────────────────────────────────────

def test_orientation_vertical_in_vertical_slot():
    # slot 160x600 is vertical (ratio 0.27)
    score = calculate_orientation_score("vertical", 160, 600)
    assert score >= 0.90

def test_orientation_horizontal_in_horizontal_slot():
    # slot 728x90 is horizontal (ratio 8.09)
    score = calculate_orientation_score("horizontal", 728, 90)
    assert score >= 0.90

def test_orientation_mismatch():
    # vertical image in a horizontal slot
    score = calculate_orientation_score("vertical", 728, 90)
    assert score <= 0.45


# ── find_best_match ────────────────────────────────────────────────────────────

MOCK_CREATIVES = [
    {"name": "banner_728x90.png",  "width": 728,  "height": 90,  "aspect_ratio": 728/90,  "orientation": "horizontal", "base64": "data:image/png;base64,fake"},
    {"name": "square_300x250.png", "width": 300,  "height": 250, "aspect_ratio": 300/250, "orientation": "horizontal", "base64": "data:image/png;base64,fake"},
    {"name": "skyscraper_160x600.png", "width": 160, "height": 600, "aspect_ratio": 160/600, "orientation": "vertical", "base64": "data:image/png;base64,fake"},
]

def test_best_match_leaderboard():
    slot = {"width": 728, "height": 90}
    match = find_best_match(slot, MOCK_CREATIVES, tolerance=35)
    assert match is not None
    assert match["name"] == "banner_728x90.png"

def test_best_match_skyscraper():
    slot = {"width": 160, "height": 600}
    match = find_best_match(slot, MOCK_CREATIVES, tolerance=35)
    assert match is not None
    assert match["name"] == "skyscraper_160x600.png"

def test_best_match_empty_creatives():
    slot = {"width": 300, "height": 250}
    assert find_best_match(slot, [], tolerance=35) is None

def test_best_match_returns_score():
    slot = {"width": 300, "height": 250}
    match = find_best_match(slot, MOCK_CREATIVES, tolerance=99999)
    assert match is not None
    assert "match_score" in match
    assert 0.0 <= match["match_score"] <= 1.0
