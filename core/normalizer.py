"""Header and unit vocabulary.

Maps column labels (Persian or English, any spelling) to canonical field
names, so an inventory file does not have to use one exact set of headers.
"""
from __future__ import annotations

from utils.text_utils import normalize_text

# --------------------------------------------------------------- headers
# Keys are already normalized with normalize_text().
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "code": (
        "code", "product code", "item code", "sku", "partnumber", "part number",
        "part no", "کد", "کد کالا", "کدکالا", "کد محصول", "کد فنی", "شناسه",
        "شناسه کالا", "کد انبار", "کد سیستم", "ردیف کد",
    ),
    "name": (
        "name", "product name", "item name", "description", "product",
        "title", "نام", "نام کالا", "نام محصول", "شرح", "شرح کالا",
        "شرح محصول", "کالا", "عنوان", "عنوان کالا", "نام و مشخصات",
    ),
    "brand": ("brand", "maker", "manufacturer", "vendor", "برند", "سازنده", "تولید کننده", "مارک"),
    "model": ("model", "type", "مدل", "تیپ", "نوع"),
    "unit": ("unit", "uom", "واحد", "واحد شمارش", "واحد سنجش"),
    "price": (
        "price", "unit price", "amount", "rate", "قیمت", "مبلغ", "فی",
        "قیمت واحد", "قیمت فروش", "بها", "نرخ", "قیمت ریال", "قیمت تومان",
    ),
    "stock": (
        "stock", "inventory", "qty", "quantity", "on hand", "balance",
        "موجودی", "موجودی انبار", "تعداد", "مانده", "مقدار", "موجود",
    ),
}

_LOOKUP: dict[str, str] = {}
for _field, _aliases in HEADER_ALIASES.items():
    for _alias in _aliases:
        _LOOKUP[normalize_text(_alias)] = _field

# --------------------------------------------------------------- units
UNIT_ALIASES = {
    "m": ("m", "metr", "meter", "متر", "مترطول", "متر طول"),
    "pcs": ("pcs", "pc", "piece", "عدد", "دستگاه", "قلم", "شاخه", "تعداد"),
    "box": ("box", "ctn", "carton", "جعبه", "کارتن", "بسته", "پک", "pack"),
    "roll": ("roll", "حلقه", "رول", "کلاف"),
    "kg": ("kg", "کیلو", "کیلوگرم"),
    "set": ("set", "ست", "سری"),
}
_UNIT_LOOKUP: dict[str, str] = {}
for _canon, _aliases in UNIT_ALIASES.items():
    for _alias in _aliases:
        _UNIT_LOOKUP[normalize_text(_alias)] = _canon


def map_header(label: str) -> str | None:
    """Return the canonical field name for a header cell, or None."""
    key = normalize_text(label)
    if not key:
        return None
    if key in _LOOKUP:
        return _LOOKUP[key]
    # tolerate extra words: "کد کالا (انبار)" -> already stripped of punctuation
    for alias, field_name in _LOOKUP.items():
        if len(alias) >= 3 and (key.startswith(alias + " ") or key.endswith(" " + alias)):
            return field_name
    return None


def normalize_unit(unit: str) -> str:
    key = normalize_text(unit)
    return _UNIT_LOOKUP.get(key, key)
