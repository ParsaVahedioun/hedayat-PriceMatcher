"""Loading of config.json with safe defaults.

All tunable numbers of the application live here, never hard-coded in the
matching or parsing logic.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    # --- matching thresholds (0-100) ---
    "exact_threshold": 99,      # identical model code            -> EXACT
    "fuzzy_threshold": 85,      # >= this and < exact             -> HIGH
    "review_threshold": 70,     # >= this and < high              -> REVIEW
    # below review_threshold nothing is shown: no price, no guess
    # if best and 2nd best candidate are closer than this *and* carry
    # different prices, the row is forced to REVIEW
    "ambiguity_margin": 4,

    # --- weights of the composite score ---
    # code: the model code written in the item name  (SCAP, VS558, SCTRW/B)
    # spec: watt / amp / volt / density / size agreement
    # text: IDF-weighted overlap of the Persian wording
    "weights": {
        "code": 0.45,
        "spec": 0.25,
        "text": 0.30,
    },
    # a disagreeing hard spec (watt, amp, volt, density) multiplies the score
    # by this, which pushes the candidate below every threshold
    "spec_conflict_factor": 0.35,
    # the brand in the item name should agree with the model-code prefix
    "brand_prefix_bonus": 4,
    # score used when the item states a rating the price row stays silent about
    "neutral_spec_score": 55,
    # penalty for a variant word ("سنسوردار", "نسوز") present on one side only
    "discriminator_penalty": 12,
    "discriminative_terms": None,   # None -> core.attributes.DEFAULT_DISCRIMINATORS
    # rescales the IDF word coverage; 1.0 = raw share, lower = more forgiving
    "text_coverage_exponent": 0.6,
    # inventory rows whose brand is not one of the price-list brands are not
    # matched at all - that is what keeps other vendors out of the result
    "restrict_to_price_list_brands": True,
    "brand_prefixes": {
        "شیله": ["SC"],
        "schiele": ["SC"],
        "ویسنا": ["VS"],
        "visena": ["VS"],
    },
    # vocabulary bridges between inventory wording and price-list wording;
    # extend these instead of touching the matching code
    "synonyms": None,        # None -> core.attributes.DEFAULT_SYNONYMS
    "context_rules": None,   # None -> core.attributes.DEFAULT_CONTEXT_RULES

    # --- candidate generation ---
    "max_candidates": 60,
    "min_token_len": 2,

    # --- PDF ---
    "ocr_enabled": True,
    "ocr_language": "fas+eng",
    "ocr_dpi": 200,
    # a page with less than this many characters is considered image-based
    "scanned_char_threshold": 40,
    # words closer than this vertically belong to the same visual row
    "pdf_row_tolerance": 3.5,
    # a price or a code continuation may sit this far from its row
    "pdf_orphan_row_gap": 12,
    "min_valid_price": 1000,    # numbers below this are not treated as a price
    "max_valid_price": 10_000_000_000,

    # --- output / misc ---
    "max_rows_in_ui": 20000,
    "log_level": "INFO",
    "pdf_font_candidates": [
        "C:/Windows/Fonts/tahoma.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
}


def app_dir() -> str:
    """Directory the app runs from (works for source runs and PyInstaller)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _local_appdata_dir() -> str:
    """Per-user writable folder, used when the exe lives somewhere read-only
    (e.g. C:\\Program Files after a proper Windows install)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "PriceMatcher")
    os.makedirs(path, exist_ok=True)
    return path


def data_dir() -> str:
    """Where config.json and logs/ actually live.

    - Source / dev runs: always next to the project (unchanged behaviour).
    - Portable build (a config.json ships right next to the exe and that
      folder is writable, e.g. a USB stick or a plain extracted zip): use
      that folder, so the app stays a single self-contained directory.
    - Installed build (Program Files, no write access for a normal user):
      fall back to %LOCALAPPDATA%\\PriceMatcher automatically.
    """
    exe_dir = app_dir()
    if not getattr(sys, "frozen", False):
        return exe_dir
    portable_config = os.path.join(exe_dir, "config.json")
    if os.path.isfile(portable_config) and os.access(exe_dir, os.W_OK):
        return exe_dir
    return _local_appdata_dir()


def config_path() -> str:
    return os.path.join(data_dir(), "config.json")


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


_cache: Dict[str, Any] | None = None


def load_config(force: bool = False) -> Dict[str, Any]:
    global _cache
    if _cache is not None and not force:
        return _cache
    data: Dict[str, Any] = {}
    path = config_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:  # broken config must never crash the app
            data = {}
    _cache = _merge(DEFAULTS, data if isinstance(data, dict) else {})
    return _cache


def save_config(values: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _merge(load_config(), values)
    with open(config_path(), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=4)
    globals()["_cache"] = cfg
    return cfg
