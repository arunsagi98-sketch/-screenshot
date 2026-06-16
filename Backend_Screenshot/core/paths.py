"""
Computed filesystem paths used throughout the application.
All paths are derived from settings — never hardcoded.
"""
import os
from functools import lru_cache

from core.config import get_settings

# Absolute path to Backend_Screenshot/
BACKEND_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Sibling Frontend_Screenshot/ directory
FRONTEND_DIR: str = os.path.normpath(os.path.join(BACKEND_ROOT, "..", "Frontend_Screenshot"))


@lru_cache(maxsize=1)
def get_paths() -> dict:
    """Return a dict of all resolved absolute paths used by the app."""
    s = get_settings()
    return {
        "screenshots": os.path.join(BACKEND_ROOT, s.screenshots_dir),
        "input_images": os.path.abspath(os.path.join(BACKEND_ROOT, s.input_images_dir)),
        "ppt_assets": os.path.join(BACKEND_ROOT, s.ppt_assets_dir),
        "ppt_format": os.path.join(BACKEND_ROOT, "PPT_Format"),
        "ppt_reports": os.path.join(BACKEND_ROOT, "ppt_reports"),
    }
