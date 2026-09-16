"""Low level text helpers (Persian / Arabic aware).

Everything here is pure Python + `re` only: no external dependency, very cheap,
safe to call on tens of thousands of rows.
"""
from __future__ import annotations

import re
import unicodedata

# ------------------------------------------------- broken PDF font glyphs
# Some Persian price lists are exported with subset fonts whose ToUnicode
# table maps a few letters to random Latin code points. The text then reads
# "مهتاƬی" instead of "مهتابی". These substitutions are applied *before*
# NFKC (Ǳ would otherwise normalize to "DZ").
PDF_GLYPH_FIXES: dict[str, str] = {
    "\u01ac": "\u0628",  # Ƭ -> ب
    "\u01aa": "\u0628",  # ƪ -> ب
    "\u01ed": "\u06cc",  # ǭ -> ی
    "\u01f1": "\u06cc",  # Ǳ -> ی
    "\u01ef": "\u06cc",  # ǯ -> ی
    "\u01fd": "\u06cc",  # ǽ -> ی
    "\u01ae": "\u067e",  # Ʈ -> پ
    "\u01b0": "\u067e",  # ư -> پ
    "\u01d7": "\u0646",  # Ǘ -> ن
    "\u01b3": "\u062a",  # Ƴ -> ت
    "\u01b1": "\u062a",  # Ʊ -> ت
}

# ---------------------------------------------------------------- characters
_CHAR_MAP = {
    "\u064a": "\u06cc",  # ARABIC YEH        -> FARSI YEH
    "\u0649": "\u06cc",  # ALEF MAKSURA      -> FARSI YEH
    "\u0626": "\u06cc",  # YEH WITH HAMZA    -> FARSI YEH
    "\u0643": "\u06a9",  # ARABIC KAF        -> KEHEH
    "\u06aa": "\u06a9",  # SWASH KAF         -> KEHEH
    "\u0629": "\u0647",  # TEH MARBUTA       -> HEH
    "\u0647\u0654": "\u0647",
    "\u0623": "\u0627",
    "\u0625": "\u0627",
    "\u0622": "\u0627",
    "\u0671": "\u0627",
    "\u0624": "\u0648",
    "\u06c0": "\u0647",
    "\u0640": "",        # TATWEEL
    "\u200c": " ",       # ZWNJ  -> space
    "\u200b": "",
    "\u200d": "",
    "\ufeff": "",
    "\u00a0": " ",
}

_DIACRITICS = re.compile(r"[\u064b-\u0652\u0653-\u0655\u0670\u06d6-\u06ed]")

_DIGIT_MAP = {}
for i in range(10):
    _DIGIT_MAP[chr(0x06F0 + i)] = str(i)   # Persian
    _DIGIT_MAP[chr(0x0660 + i)] = str(i)   # Arabic-Indic
_DIGIT_TRANS = str.maketrans(_DIGIT_MAP)

_DASHES = dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u06d4", "-")
_SLASHES = dict.fromkeys("\u2044\u2215", "/")
_PUNCT_TRANS = str.maketrans({**_DASHES, **_SLASHES})

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_GLUE_RE = re.compile(r"(?<=[a-z])[\s\-_/]+(?=\d)")
_GLUE_RE2 = re.compile(r"(?<=\d)[\s\-_/]+(?=[a-z])")

_LATIN_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_/\.]*")
_PERSIAN_CHAR = re.compile(r"[\u0600-\u06ff]")


def fix_pdf_glyphs(text: str) -> str:
    """Repair the broken Latin code points some subset fonts emit."""
    if not text:
        return ""
    for src, dst in PDF_GLYPH_FIXES.items():
        if src in text:
            text = text.replace(src, dst)
    return text


def shape_to_plain(text: str) -> str:
    """Arabic presentation forms (ﻣﻬﺘﺎﺑﯽ) -> plain letters (مهتابی).

    PDF extraction very often returns the shaped glyph forms; they are
    different code points, so any comparison against Excel text fails unless
    they are folded back first.
    """
    if not text:
        return ""
    return unicodedata.normalize("NFKC", fix_pdf_glyphs(text))


def fix_persian_chars(text: str) -> str:
    """Unify Arabic/Persian look-alike characters."""
    if not text:
        return ""
    text = fix_pdf_glyphs(text)
    for src, dst in _CHAR_MAP.items():
        if src in text:
            text = text.replace(src, dst)
    return _DIACRITICS.sub("", text)


def to_english_digits(text: str) -> str:
    """۱۲۳۴۵ / ١٢٣٤٥ -> 12345"""
    if not text:
        return ""
    return text.translate(_DIGIT_TRANS)


def clean_spaces(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip()


def split_latin_persian(text: str) -> str:
    """Insert a space between a Latin/digit run and Persian letters.

    PDF rows arrive glued together ("وات15", "ردار2,200,000"); without this
    the tokens are unusable.
    """
    if not text:
        return ""
    out: list[str] = []
    last = 0
    for match in _LATIN_RUN.finditer(text):
        start, end = match.span()
        before = text[last:start]
        out.append(before)
        if before and _PERSIAN_CHAR.match(before[-1:]):
            out.append(" ")
        out.append(match.group(0))
        if _PERSIAN_CHAR.match(text[end:end + 1]):
            out.append(" ")
        last = end
    out.append(text[last:])
    return clean_spaces("".join(out))


def normalize_text(text: str, glue_alnum: bool = True) -> str:
    """Full normalization used as the matching key for names/brands/models."""
    if text is None:
        return ""
    text = str(text)
    if not text.strip():
        return ""
    text = shape_to_plain(text)
    text = fix_persian_chars(text)
    text = to_english_digits(text)
    text = text.translate(_PUNCT_TRANS)
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = clean_spaces(text)
    if glue_alnum and text:
        text = _GLUE_RE.sub("", text)
        text = _GLUE_RE2.sub("", text)
    return text


def normalize_code(code: str) -> str:
    """Product code key: digits + latin letters only, uppercase."""
    if code is None:
        return ""
    code = shape_to_plain(str(code))
    code = to_english_digits(fix_persian_chars(code))
    code = re.sub(r"[^0-9A-Za-z]", "", code).upper()
    if code.isdigit():
        code = code.lstrip("0") or "0"
    return code


def code_family(code: str) -> str:
    """Leading letter run of a model code: "SCAP-42-S2" -> "SCAP"."""
    key = normalize_code(code)
    match = re.match(r"[A-Z]+", key)
    return match.group(0) if match else ""


def tokens(text: str) -> list[str]:
    return [t for t in normalize_text(text).split(" ") if t]


def dense(text: str) -> str:
    """Normalized text with every space removed.

    PDF extraction splits Persian words at arbitrary points ("مد ل تو ان"),
    so word boundaries coming out of a PDF carry no information. Comparing
    the space-free form instead makes substring tests work again:
    "مدلتوانرنگنور" still contains "توان".
    """
    return normalize_text(text).replace(" ", "")
