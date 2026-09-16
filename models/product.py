"""Data models.

`slots=True` is used everywhere: with tens of thousands of rows this saves a
large amount of RAM compared to plain dict-based objects, which matters on the
low-end machines this tool is meant to run on.

Two distinct shapes are used on purpose:

* `PriceItem`  - one row of the PDF price list (model code + price + specs)
* `StockItem`  - one row of the Excel inventory (item code + name + stock)

The output is always driven by the inventory: every Excel row produces exactly
one result row, and a PDF row that has no counterpart in the inventory is
simply dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------- statuses
STATUS_EXACT = "EXACT"
STATUS_HIGH = "HIGH"
STATUS_REVIEW = "REVIEW"
STATUS_NOT_FOUND = "NOT_FOUND"

MATCH_EXACT_CODE = "exact_code"
MATCH_CODE_SPEC = "code_spec"
MATCH_TEXT = "text"
MATCH_NONE = "none"


@dataclass(slots=True)
class PriceItem:
    """One product row of the PDF price list."""

    code: str = ""                 # "SCAP-12"
    price: float | None = None
    text: str = ""                 # persian description of the row itself
    section_fa: str = ""           # persian title of the table it belongs to
    section_en: str = ""           # latin title of the same table
    page: int = 0

    # derived
    code_key: str = ""             # "SCAP12"
    family: str = ""               # "SCAP"
    context: str = ""              # normalized section + row text
    specs: dict = field(default_factory=dict)
    tokens: tuple = ()

    @property
    def label(self) -> str:
        parts = [self.section_fa.strip(), self.text.strip()]
        return " | ".join(p for p in parts if p)


@dataclass(slots=True)
class StockItem:
    """One row of the Excel inventory - this is what the user sees."""

    code: str = ""                 # the warehouse item code (کد کالا)
    name: str = ""
    stock: float | None = None
    unit: str = ""
    row: int = 0

    # derived
    name_key: str = ""
    expanded: str = ""             # name_key + synonym expansions
    brand: str = ""
    codes: list = field(default_factory=list)   # latin codes found in the name
    specs: dict = field(default_factory=dict)
    tokens: tuple = ()


@dataclass(slots=True)
class MatchResult:
    """An inventory row joined (or not) with a price-list row."""

    item: StockItem
    matched: PriceItem | None = None
    score: float = 0.0
    match_type: str = MATCH_NONE
    status: str = STATUS_NOT_FOUND
    note: str = ""
    alternatives: list = field(default_factory=list)

    def to_dict(self) -> dict:
        matched = self.matched
        return {
            "code": self.item.code,
            "name": self.item.name,
            "stock": self.item.stock,
            "price": matched.price if matched else None,
            "pdf_code": matched.code if matched else "",
            "pdf_name": matched.label if matched else "",
            "pdf_page": matched.page if matched else 0,
            "score": round(self.score, 1),
            "match_type": self.match_type,
            "status": self.status,
            "note": self.note,
            "alternatives": self.alternatives,
        }
