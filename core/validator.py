"""Sanity checks and cleanup between extraction and matching."""
from __future__ import annotations

from core.errors import PdfError
from models.product import PriceItem, StockItem
from utils.logger import get_logger

log = get_logger("validator")


def clean_price_items(items: list[PriceItem], config: dict) -> tuple[list[PriceItem], dict]:
    """Drop junk rows from the price list and merge duplicates.

    Duplicate rule: same model code -> keep the first occurrence, so a product
    repeated in a page header or an index page is not counted twice.
    """
    min_price = float(config.get("min_valid_price", 0))
    max_price = float(config.get("max_valid_price", float("inf")))

    report = {"input": len(items), "dropped_no_price": 0, "duplicates": 0}
    seen: set[str] = set()
    clean: list[PriceItem] = []

    for item in items:
        if item.price is None or not (min_price <= item.price <= max_price):
            report["dropped_no_price"] += 1
            continue
        if not item.code_key and not item.context:
            report["dropped_no_price"] += 1
            continue
        key = item.code_key or ("t:" + item.context)
        if key in seen:
            report["duplicates"] += 1
            continue
        seen.add(key)
        clean.append(item)

    report["output"] = len(clean)
    log.info("validator(price): %s", report)

    if not clean:
        raise PdfError(
            "هیچ کالایی با قیمت معتبر از PDF استخراج نشد.\n"
            "ساختار فایل ممکن است پشتیبانی نشود یا PDF اسکن‌شده باشد.",
            str(report),
        )
    return clean, report


def clean_stock_items(items: list[StockItem]) -> tuple[list[StockItem], dict]:
    """Remove rows with no usable key from the inventory."""
    report = {"input": len(items), "dropped": 0, "no_stock_value": 0}
    clean: list[StockItem] = []
    for item in items:
        if not item.code and not item.name_key:
            report["dropped"] += 1
            continue
        if item.stock is None:
            report["no_stock_value"] += 1
        clean.append(item)
    report["output"] = len(clean)
    log.info("validator(stock): %s", report)
    return clean, report
