"""Parsing of prices and stock quantities coming from PDF text / Excel cells."""
from __future__ import annotations

import re

from utils.text_utils import fix_persian_chars, to_english_digits

# 1,250,000 | 1.250.000 | 1 250 000 | 1250000 | 1250000.50 | ۱،۲۵۰،۰۰۰
_NUM_RE = re.compile(r"\d{1,3}(?:[.,\u066c\u066b\u060c\s]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?")
_SEPS = "\u066c\u066b\u060c,"  # arabic thousands sep, arabic decimal sep, plain arabic comma, comma


def _clean_number(raw: str) -> str:
    raw = to_english_digits(fix_persian_chars(raw)).strip()
    raw = re.sub(r"\s", "", raw)
    for sep in _SEPS:
        raw = raw.replace(sep, ",")
    # decide whether "." / "," are thousand separators or a decimal point
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")
    elif "," in raw:
        parts = raw.split(",")
        if all(len(p) == 3 for p in parts[1:]):
            raw = "".join(parts)
        else:
            raw = ".".join(parts)
    elif "." in raw:
        parts = raw.split(".")
        if len(parts) > 2 or all(len(p) == 3 for p in parts[1:]):
            raw = "".join(parts)
    return raw


def parse_number(value) -> float | None:
    """Return the first number found in `value`, or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = to_english_digits(fix_persian_chars(str(value)))
    match = _NUM_RE.search(text)
    if not match:
        return None
    try:
        return float(_clean_number(match.group(0)))
    except ValueError:
        return None


def find_numbers(text: str) -> list[tuple[float, int, int]]:
    """All numbers in a line as (value, start, end) - used by the PDF parser."""
    text = to_english_digits(fix_persian_chars(text or ""))
    out: list[tuple[float, int, int]] = []
    for match in _NUM_RE.finditer(text):
        try:
            out.append((float(_clean_number(match.group(0))), match.start(), match.end()))
        except ValueError:
            continue
    return out


def parse_price(value, min_price: float = 0, max_price: float = float("inf")):
    number = parse_number(value)
    if number is None:
        return None
    if number < min_price or number > max_price:
        return None
    return number


def parse_stock(value) -> float | None:
    number = parse_number(value)
    if number is None:
        return None
    return number


def format_price(value) -> str:
    if value is None:
        return "-"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"
