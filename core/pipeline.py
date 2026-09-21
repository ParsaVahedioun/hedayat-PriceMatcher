"""The whole processing pipeline in one place, UI-independent.

Used both by the pywebview bridge and by the headless CLI mode, which makes
the core testable without starting a window.

Direction matters: the Excel inventory is read first and drives everything.
Every inventory row ends up in the result exactly once; price-list rows that
match nothing in the inventory are never emitted.
"""
from __future__ import annotations

import os
import time
from typing import Callable

from core.errors import AppError
from core.excel_reader import read_excel
from core.matcher import Matcher, prepare_stock, summarize
from core.pdf_reader import read_pdf
from core.validator import clean_price_items, clean_stock_items
from models.product import STATUS_EXACT, STATUS_HIGH, STATUS_REVIEW
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


def run_batch(pdf_entries: list[dict], excel_path: str, progress: ProgressFn | None = None,
              config: dict | None = None) -> dict:
    """Match one Excel inventory against several PDF price lists at once.

    `pdf_entries` is a list of `{"path": ..., "brand": ..., "name": ...}`.
    Every PDF is read and matched *independently* (its own brand, its own
    candidate pool) exactly as `run()` would do it alone, one file at a time
    - "name" is only a display label. The results are then merged row by
    row: the first PDF in the list that prices a given inventory row keeps
    that price; a PDF later in the list only ever fills in rows that are
    still unpriced, it never overwrites an earlier price. This makes the
    list order meaningful: put the price list you trust most first.

    Every inventory row still comes back exactly once, now carrying a
    "source" key naming which PDF supplied its price (empty if none did),
    and `stats["files"]` reports on each PDF on its own - rows read, rows
    priced, and whether it failed outright - so one bad file never hides
    what the others found.
    """
    progress = progress or _noop
    entries = [dict(entry) for entry in (pdf_entries or []) if (entry.get("path") or "").strip()]
    if not entries:
        raise AppError("هیچ فایل PDF‌ای برای پردازش انتخاب نشده است.")

    base_cfg = dict(config or load_config())
    started = time.time()
    total_files = len(entries)

    combined_rows: list[dict] | None = None
    files_report: list[dict] = []
    pdf_rows_total = 0

    for file_index, entry in enumerate(entries):
        pdf_path = entry.get("path", "")
        brand = (entry.get("brand") or "").strip()
        label = (entry.get("name") or os.path.basename(pdf_path) or pdf_path)

        def sub_progress(percent: int, message: str, _idx=file_index, _label=label) -> None:
            overall = int(100 * _idx / total_files + percent / total_files)
            progress(min(99, overall), f"[{_idx + 1}/{total_files}] {_label}: {message}")

        file_started = time.time()
        try:
            result = run(pdf_path, excel_path, sub_progress, config=base_cfg, brand=brand)
        except AppError as exc:
            files_report.append({
                "path": pdf_path, "name": label, "brand": brand, "ok": False,
                "error": exc.message, "pdf_rows": 0, "priced": 0,
                "elapsed": round(time.time() - file_started, 2),
            })
            log.warning("batch: %s failed: %s", label, exc.message)
            continue

        rows = result["rows"]
        pdf_rows_total += result["stats"].get("pdf_rows", 0)

        if combined_rows is None:
            combined_rows = []
            file_priced = 0
            for row in rows:
                row = dict(row)
                if row.get("price") is not None:
                    row["source"] = label
                    file_priced += 1
                else:
                    row["source"] = ""
                combined_rows.append(row)
        else:
            file_priced = 0
            for position, row in enumerate(rows):
                if position >= len(combined_rows):
                    break
                current = combined_rows[position]
                if current.get("price") is None and row.get("price") is not None:
                    row = dict(row)
                    row["source"] = label
                    combined_rows[position] = row
                    file_priced += 1

        files_report.append({
            "path": pdf_path, "name": label, "brand": brand, "ok": True,
            "pdf_rows": result["stats"].get("pdf_rows", 0), "priced": file_priced,
            "elapsed": round(time.time() - file_started, 2),
        })

    if combined_rows is None:
        raise AppError(
            "هیچ‌یک از فایل‌های PDF پردازش نشد.",
            "; ".join(f"{f['name']}: {f.get('error', '')}" for f in files_report),
        )

    exact = sum(1 for row in combined_rows if row.get("status") == STATUS_EXACT)
    high = sum(1 for row in combined_rows if row.get("status") == STATUS_HIGH)
    review = sum(1 for row in combined_rows if row.get("status") == STATUS_REVIEW)
    priced = sum(1 for row in combined_rows if row.get("price") is not None)
    total = len(combined_rows)

    stats = {
        "total": total, "exact": exact, "high": high, "review": review,
        "not_found": total - exact - high - review, "priced": priced,
        "elapsed": round(time.time() - started, 2),
        "pdf_rows": pdf_rows_total, "excel_rows": total,
        "brand": "، ".join(dict.fromkeys(f["brand"] for f in files_report if f.get("brand"))),
        "files": files_report,
    }
    log.info("batch pipeline done in %.2fs over %d file(s): priced=%d/%d",
             stats["elapsed"], total_files, priced, total)
    progress(100, "پایان")

    return {"rows": combined_rows, "stats": stats, "files": files_report}
