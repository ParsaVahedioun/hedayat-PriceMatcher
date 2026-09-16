"""The whole processing pipeline in one place, UI-independent.

Used both by the pywebview bridge and by the headless CLI mode, which makes
the core testable without starting a window.

Direction matters: the Excel inventory is read first and drives everything.
Every inventory row ends up in the result exactly once; price-list rows that
match nothing in the inventory are never emitted.
"""
from __future__ import annotations

import time
from typing import Callable

from core.excel_reader import read_excel
from core.matcher import Matcher, prepare_stock, summarize
from core.pdf_reader import read_pdf
from core.validator import clean_price_items, clean_stock_items
from utils.config import load_config
from utils.logger import get_logger

log = get_logger("pipeline")

ProgressFn = Callable[[int, str], None]


def _noop(percent: int, message: str) -> None:  # pragma: no cover
    pass


def run(pdf_path: str, excel_path: str, progress: ProgressFn | None = None,
        config: dict | None = None, brand: str = "") -> dict:
    progress = progress or _noop
    cfg = dict(config or load_config())
    brand = (brand or "").strip()
    if brand:
        # a brand typed in for this run locks matching to inventory rows
        # that carry that exact brand word, regardless of the generic
        # brand-prefix table or the restrict_to_price_list_brands toggle
        cfg["target_brand"] = brand
        cfg["restrict_to_price_list_brands"] = True
    started = time.time()

    progress(3, "در حال خواندن PDF...")
    price_items = read_pdf(
        pdf_path, cfg,
        progress=lambda i, total: progress(3 + int(22 * i / max(1, total)),
                                           "در حال خواندن PDF..."),
    )
    price_items, price_report = clean_price_items(price_items, cfg)

    progress(28, "در حال خواندن Excel...")
    stock_items = read_excel(excel_path)
    stock_items = [prepare_stock(item, cfg) for item in stock_items]
    stock_items, stock_report = clean_stock_items(stock_items)

    progress(45, "در حال تطبیق کالاها...")
    matcher = Matcher(cfg)
    results = matcher.match_all(
        stock_items, price_items,
        progress=lambda i, total: progress(45 + int(45 * i / max(1, total)),
                                           "در حال تطبیق کالاها..."),
    )

    progress(92, "در حال آماده‌سازی نتیجه...")
    rows = [result.to_dict() for result in results]
    stats = summarize(results)
    elapsed = time.time() - started
    stats["elapsed"] = round(elapsed, 2)
    stats["pdf_rows"] = len(price_items)
    stats["excel_rows"] = len(stock_items)
    stats["brand"] = brand
    log.info("pipeline done in %.2fs: %s", elapsed, stats)
    progress(100, "پایان")

    return {
        "rows": rows,
        "stats": stats,
        "report": {"pdf": price_report, "excel": stock_report},
    }
