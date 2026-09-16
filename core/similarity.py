"""String similarity backend.

RapidFuzz is used when available (C++ speed, the intended production path).
A small pure-Python fallback keeps the app and the test-suite working if the
wheel is missing, so a broken install never breaks the whole tool.
"""
from __future__ import annotations

from difflib import SequenceMatcher

try:  # pragma: no cover - depends on environment
    from rapidfuzz import fuzz as _fuzz

    HAS_RAPIDFUZZ = True
except Exception:  # pragma: no cover
    _fuzz = None
    HAS_RAPIDFUZZ = False


def _plain_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0
    return SequenceMatcher(None, a, b).ratio() * 100.0


def _fallback_token_set_ratio(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    common = ta & tb
    only_a = " ".join(sorted(ta - common))
    only_b = " ".join(sorted(tb - common))
    base = " ".join(sorted(common))
    s1 = (base + " " + only_a).strip()
    s2 = (base + " " + only_b).strip()
    return max(
        _plain_ratio(base, s1),
        _plain_ratio(base, s2),
        _plain_ratio(s1, s2),
    )


def ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if _fuzz is not None:
        return float(_fuzz.ratio(a, b))
    return _plain_ratio(a, b)


def token_set_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0
    if _fuzz is not None:
        return float(_fuzz.token_set_ratio(a, b))
    return _fallback_token_set_ratio(a, b)


def token_sort_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if _fuzz is not None:
        return float(_fuzz.token_sort_ratio(a, b))
    return _plain_ratio(" ".join(sorted(a.split())), " ".join(sorted(b.split())))


def partial_ratio(a: str, b: str) -> float:
    """Best alignment of the shorter string inside the longer one.

    Used against PDF text, which carries a lot of filler around the part that
    actually corresponds to the inventory name.
    """
    if not a or not b:
        return 0.0
    if _fuzz is not None:
        return float(_fuzz.partial_ratio(a, b))
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if short in long:
        return 100.0
    best = 0.0
    window = len(short)
    for start in range(0, max(1, len(long) - window + 1)):
        best = max(best, _plain_ratio(short, long[start:start + window]))
    return best


def name_similarity(a: str, b: str) -> float:
    """Blend used for product names.

    token_set_ratio alone happily returns 100 for "cat6" vs "cat6 sftp"
    (a subset match), which is exactly the wrong answer for a price list.
    Averaging it with the strict ratio keeps subsets clearly below 100.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0
    strict = ratio(a, b)
    loose = token_set_ratio(a, b)
    return 0.5 * strict + 0.5 * loose
