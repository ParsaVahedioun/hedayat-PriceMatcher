"""Technical attributes of a product, pulled out of its Persian description.

Product names in an Iranian electrical inventory are not free prose: they are
a fixed recipe of *category + numeric specs + colour + brand*, e.g.

    "پنل SMD توکار آ پلاست 9 وات گرد مهتابی شیله (SCAP)"
    "کلید مینیاتوری تک فاز 16 آمپر (استاندارد) تیپ C ویسنا"

The numbers are what actually identify a row inside a family - a 9 W panel and
an 18 W panel of the same family are two different prices. Fuzzy string
similarity alone treats "9" and "18" as a one-character difference, which is
exactly how a price list gets mis-matched, so every numeric spec is extracted
here and compared as a hard constraint later on.
"""
from __future__ import annotations

import re

from utils.text_utils import (
    clean_spaces,
    dense,
    fix_persian_chars,
    normalize_code,
    normalize_text,
    split_latin_persian,
    to_english_digits,
)

# --------------------------------------------------------------- unit specs
# Each spec: canonical name -> the Persian/Latin unit words that follow (or
# precede) the number. PDF rows often arrive with the number glued *after*
# the unit ("وات15"), so both orders are searched.
# a number that does not continue a Latin token: "12V" is a voltage,
# the "40" inside the model code "SC40A" is not an amperage
_NUM = r"(?<![A-Za-z])(\d+(?:[./]\d+)?)"
# `\b` cannot be used after a Persian unit: spec_text() packs Persian words
# together, so "وات" is followed by another letter far more often than not
_END = r"(?![A-Za-z0-9])"
_RANGE = r"(\d+)\s*(?:تا|-|to)\s*(\d+)"

SPEC_UNITS: dict[str, tuple[str, ...]] = {
    "watt": ("وات", "w"),
    "amp": ("امپر", "امر"),
    "volt": ("ولت", "v"),
    "density": ("تراکم",),
    "degree": ("درجه",),
    "ip": ("ip",),
}

_UNIT_RE: dict[str, tuple[re.Pattern, re.Pattern, re.Pattern]] = {}
for _spec, _units in SPEC_UNITS.items():
    _alt = "|".join(_units)
    _UNIT_RE[_spec] = (
        re.compile(_NUM + r"\s*(?:" + _alt + r")" + _END),     # 15 وات
        re.compile(r"(?:" + _alt + r")\s*" + _NUM),            # وات 15
        re.compile(_RANGE + r"\s*(?:" + _alt + r")" + _END),   # 6 تا 32 آمپر
    )

_MM_RE = re.compile(r"(\d+)\s*(?:میلی\s*متر|میلیمتر|mm)" + _END)
_CM_RE = re.compile(r"(\d+)\s*(?:سانتی\s*متر|سانتیمتر|سانتی|سانت|cm)" + _END)
_DIM_RE = re.compile(r"\d+(?:\s*[*x×]\s*\d+)+")

# ------------------------------------------------------------ vocabulary
# Words that mean the same thing in an inventory name and in a price list.
# Kept here (and overridable from config.json) instead of being hidden in the
# scoring code, because this is the part an end user may need to extend.
DEFAULT_SYNONYMS: dict[str, str] = {
    "تکفاز": "تک پل",
    "دوفاز": "دو پل",
    "سهفاز": "سه پل",
    "چهارفاز": "چهار پل",
    "تک فاز": "تک پل",
    "دو فاز": "دو پل",
    "سه فاز": "سه پل",
    "چهار فاز": "چهار پل",
    "سنسور دار": "سنسوردار",
    "وایرلس": "بدون سیم",
    "نقره ای پلاس": "سیلور پلاس",
    "رابط": "درایور",
    "چراغ خطی": "براکت",
    "فنر متغییر": "فنر متحرک",
    "فنر متغیر": "فنر متحرک",
    "اپلاست": "ا پلاست",
    "ا پلاست": "اپلاست",
    "روکار": "رو کار",
    "توکار": "تو کار",
    "مینیاتوری": "مینیاتور",
    "پروژکتور": "پرولایت",
    "شلنگی": "بدون سیم",
}

# Conditional rules: when *all* `when` terms are present, `add` terms are
# appended to the text used for similarity. This models domain equivalences
# that are not plain word-for-word synonyms.
DEFAULT_CONTEXT_RULES: list[dict] = [
    # a single-phase RCCB is physically a 2-pole device, a three-phase one 4-pole
    {"when": ["محافظ جان", "تک فاز"], "add": ["دو پل"]},
    {"when": ["محافظ جان", "سه فاز"], "add": ["چهار پل"]},
    {"when": ["محافظ جان", "ترکیبی"], "add": ["rcbo", "ترکیبی دو پل"]},
    {"when": ["چراغ خطی"], "add": ["براکت فول لایت"]},
    {"when": ["ریسه", "شلنگی"], "add": ["ریسه روشنایی بدون سیم"]},
]

# Words that must agree on both sides. They mark a *variant*, not a detail:
# a sensor panel and a plain panel of the same family are different products
# at very different prices, and the only thing telling them apart is this one
# word. Their presence on one side but not the other is penalised.
DEFAULT_DISCRIMINATORS: tuple[str, ...] = (
    "سنسوردار", "اضطراری", "نسوز", "ترکیبی", "متحرک", "دیواری",
    "rgb", "ip64", "ip66", "اسلیم لاین", "واید لاین", "سیلور پلاس",
    "درایور", "کانکتور", "منبع تغذیه", "ریموت",
    # category words: they keep a breaker from being priced as an RCCB
    "محافظ جان", "مینیاتوری", "چسب برق",
)

# brand word in the inventory  ->  model-code prefix used in the price list
DEFAULT_BRAND_PREFIXES: dict[str, tuple[str, ...]] = {
    "شیله": ("SC",),
    "schiele": ("SC",),
    "ویسنا": ("VS",),
    "visena": ("VS",),
}

_CODE_IN_NAME = re.compile(r"\b[A-Za-z]{2,}[A-Za-z0-9]*(?:[\-/][A-Za-z0-9]+)*\b")
# tokens that look like a code but are just spec words
_CODE_STOPWORDS = {
    "SMD", "COB", "DOB", "LED", "IP", "IP20", "IP44", "IP65", "IP66", "IP64",
    "RGB", "PVC", "AC", "DC", "PRO", "BASIC", "NEW", "K", "W", "V", "A",
    "CM", "MM", "KA", "PIR", "E27", "E14", "MR16", "GU10", "RCBO", "RCCB", "MCB",
}


def _first(pattern: re.Pattern, text: str) -> float | None:
    match = pattern.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace("/", "."))
    except (ValueError, IndexError):
        return None


def _all_numbers(pattern: re.Pattern, text: str) -> list[float]:
    out: list[float] = []
    for match in pattern.finditer(text):
        try:
            out.append(float(match.group(1).replace("/", ".")))
        except (ValueError, IndexError):
            continue
    return out


_PERSIAN_GAP = re.compile(r"(?<=[\u0600-\u06ff]) +(?=[\u0600-\u06ff])")


def spec_text(raw: str) -> str:
    """Normalized form used by every extractor below.

    Spaces *between Persian letters* are removed: PDF extraction splits words
    at arbitrary points ("آ مپر", "میلی متر"), so a gap inside Persian text
    carries no information and would otherwise break every unit pattern.
    Gaps next to a digit or a Latin run are kept - those are real.
    """
    # digits first: Persian digits have to become Latin before the Latin/
    # Persian split can see them as a number
    text = to_english_digits(fix_persian_chars(str(raw or "")))
    text = split_latin_persian(text)
    text = text.replace("\u066b", ".").replace("\u066c", ",")
    text = re.sub(r"[()\[\]،,؛:]", " ", text)
    text = clean_spaces(text.lower())
    return _PERSIAN_GAP.sub("", text)


def extract_specs(raw: str) -> dict:
    """Return the numeric fingerprint of a product description."""
    text = spec_text(raw)
    specs: dict = {}

    for name, (after, before, ranged) in _UNIT_RE.items():
        match = ranged.search(text)
        if match:
            try:
                low, high = float(match.group(1)), float(match.group(2))
                specs[name] = low
                specs[name + "_range"] = (min(low, high), max(low, high))
                continue
            except ValueError:
                pass
        value = _first(after, text)
        if value is None:
            value = _first(before, text)
        if value is not None:
            specs[name] = value

    mm = _all_numbers(_MM_RE, text)
    cm = _all_numbers(_CM_RE, text)
    if cm:
        mm = mm + [v * 10 for v in cm]
        specs["cm"] = cm[0]
    if mm:
        specs["mm"] = sorted(set(mm))

    dims: list[int] = []
    for match in _DIM_RE.finditer(text):
        for part in re.split(r"[*x×]", match.group(0)):
            part = part.strip()
            if part.isdigit():
                dims.append(int(part))
    if dims:
        specs["dims"] = sorted(set(dims))

    # every standalone integer of the description, used as weak evidence when
    # a column heading was lost and a value ended up as a bare number
    specs["numbers"] = sorted({
        int(token) for token in re.findall(r"(?<![A-Za-z.])(\d{1,4})(?![\d.])", text)
    })

    return specs


def extract_codes(raw: str) -> list[str]:
    """Latin model codes mentioned inside a product name.

    "پنل ... شیله (SCAP)" -> ["SCAP"];  "... (SCTRW/B)" -> ["SCTRWB"].
    Spec words such as SMD / COB / IP20 are filtered out, otherwise every
    LED product in the inventory would claim the same "code".
    """
    text = split_latin_persian(str(raw or ""))
    out: list[str] = []
    for match in _CODE_IN_NAME.finditer(text):
        token = match.group(0)
        key = normalize_code(token)
        if not key or len(key) < 3:
            continue
        if key in _CODE_STOPWORDS or token.upper() in _CODE_STOPWORDS:
            continue
        if not re.match(r"[A-Za-z]{2,}", token):
            continue
        if key not in out:
            out.append(key)
    return out


def detect_brand(raw: str, brand_prefixes: dict | None = None) -> str:
    """Which price-list brand a row belongs to (empty when none applies)."""
    table = brand_prefixes or DEFAULT_BRAND_PREFIXES
    # dense (space-free), not normalize_text: "امید نور" and "امیدنور" name
    # the same brand, and a Persian PDF/Excel author is never consistent
    # about the space between the two halves of a compound brand name.
    key = dense(raw)
    for brand in table:
        if dense(brand) and dense(brand) in key:
            return brand
    return ""


def expand_synonyms(raw: str, synonyms: dict | None = None,
                    rules: list | None = None) -> str:
    """Append equivalent wordings so both sides use the same vocabulary."""
    table = DEFAULT_SYNONYMS if synonyms is None else synonyms
    rule_list = DEFAULT_CONTEXT_RULES if rules is None else rules
    base = normalize_text(raw)
    extra: list[str] = []
    for source, target in table.items():
        if normalize_text(source) and normalize_text(source) in base:
            extra.append(normalize_text(target))
    for rule in rule_list:
        needed = [normalize_text(w) for w in rule.get("when", [])]
        if needed and all(w in base for w in needed):
            extra.extend(normalize_text(w) for w in rule.get("add", []))
    if not extra:
        return base
    return clean_spaces(base + " " + " ".join(extra))
