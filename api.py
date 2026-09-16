"""The Python side of the pywebview bridge.

JavaScript only renders; every piece of business logic lives behind these
methods. Long work runs in a worker thread so the window never freezes.
"""
from __future__ import annotations

import json
import os
import threading
import time

from core import pipeline
from core.errors import AppError
from core.exporter import export_excel, export_pdf
from utils.config import load_config, save_config
from utils.logger import get_logger

log = get_logger("api")


class Api:
    def __init__(self):
        self.window = None
        self.pdf_path: str = ""
        self.excel_path: str = ""
        self.brand: str = ""
        self.rows: list[dict] = []
        self.stats: dict = {}
        self._busy = False
        self._lock = threading.Lock()

    # --------------------------------------------------------- utilities
    def _ok(self, **payload) -> dict:
        payload["ok"] = True
        return payload

    def _fail(self, message: str, detail: str = "") -> dict:
        return {"ok": False, "error": message, "detail": detail}

    def _emit(self, event: str, data: dict) -> None:
        """Push an event to the UI (progress / done / error)."""
        if self.window is None:
            return
        try:
            self.window.evaluate_js(f"window.onPyEvent({json.dumps(event)}, {json.dumps(data, ensure_ascii=False)})")
        except Exception as exc:  # window closed mid-work
            log.warning("emit failed: %s", exc)

    # ------------------------------------------------------ file pickers
    def select_pdf(self) -> dict:
        path = self._pick_file(("PDF (*.pdf)",))
        if path:
            self.pdf_path = path
            return self._ok(path=path, name=os.path.basename(path))
        return self._fail("فایلی انتخاب نشد.")

    def select_excel(self) -> dict:
        path = self._pick_file(("Excel (*.xlsx;*.xlsm)",))
        if path:
            self.excel_path = path
            return self._ok(path=path, name=os.path.basename(path))
        return self._fail("فایلی انتخاب نشد.")

    def _pick_file(self, file_types) -> str:
        import webview

        result = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types)
        if not result:
            return ""
        return result[0] if isinstance(result, (list, tuple)) else str(result)

    # --------------------------------------------------------- processing
    def process_files(self, brand: str = "") -> dict:
        if self._busy:
            return self._fail("پردازش دیگری در حال اجراست.")
        if not self.pdf_path:
            return self._fail("فایل PDF لیست قیمت انتخاب نشده است.")
        if not self.excel_path:
            return self._fail("فایل Excel انبار انتخاب نشده است.")
        brand = (brand or "").strip()
        if not brand:
            return self._fail("نام برند لیست قیمت وارد نشده است.")
        self.brand = brand
        self._busy = True
        threading.Thread(target=self._worker, daemon=True).start()
        return self._ok(started=True)

    def _worker(self) -> None:
        try:
            def progress(percent: int, message: str) -> None:
                self._emit("progress", {"percent": percent, "message": message})

            result = pipeline.run(self.pdf_path, self.excel_path, progress, brand=self.brand)
            with self._lock:
                self.rows = result["rows"]
                self.stats = result["stats"]
            self._emit("done", {"stats": result["stats"], "count": len(result["rows"])})
        except AppError as exc:
            log.error("pipeline error: %s | %s", exc.message, exc.detail)
            self._emit("error", {"message": exc.message})
        except Exception as exc:  # never show a raw traceback to the user
            log.exception("unexpected pipeline failure")
            self._emit("error", {"message": "خطای غیرمنتظره در پردازش. جزئیات در logs/app.log ثبت شد."})
        finally:
            self._busy = False

    # ------------------------------------------------------------ results
    def get_results(self, offset: int = 0, limit: int = 0) -> dict:
        with self._lock:
            rows = self.rows
            stats = self.stats
        if limit:
            rows = rows[offset: offset + limit]
        return self._ok(rows=rows, stats=stats, total=len(self.rows))

    # ------------------------------------------------------------ exports
    def export_excel(self, only_priced: bool = True) -> dict:
        # the excel output always mirrors the full inventory - priced and
        # unpriced rows alike - exactly like the warehouse's own file does
        return self._export("xlsx", False)

    def export_pdf(self, only_priced: bool = True) -> dict:
        return self._export("pdf", only_priced)

    def _export(self, kind: str, only_priced: bool = True) -> dict:
        if not self.rows:
            return self._fail("نتیجه‌ای برای خروجی گرفتن وجود ندارد.")
        rows = [row for row in self.rows if row.get("price") is not None] \
            if only_priced else list(self.rows)
        if not rows:
            return self._fail("هیچ کالایی قیمت پیدا نکرد.")
        brand_slug = "".join(ch for ch in self.brand if ch not in '\\/:*?"<>|').strip()
        prefix = f"price-match-{brand_slug}-" if brand_slug else "price-match-"
        default_name = time.strftime(f"{prefix}%Y%m%d-%H%M.{kind}")
        try:
            import webview

            path = self.window.create_file_dialog(
                webview.SAVE_DIALOG, save_filename=default_name,
                file_types=(f"{kind.upper()} (*.{kind})",),
            )
            if isinstance(path, (list, tuple)):
                path = path[0] if path else ""
        except Exception as exc:
            log.warning("save dialog failed: %s", exc)
            path = os.path.join(os.path.expanduser("~"), default_name)
        if not path:
            return self._fail("مسیر ذخیره انتخاب نشد.")
        path = str(path)
        if not path.lower().endswith("." + kind):
            path += "." + kind
        try:
            if kind == "xlsx":
                export_excel(rows, path)
            else:
                export_pdf(rows, path, self.stats)
        except AppError as exc:
            return self._fail(exc.message, exc.detail)
        except Exception as exc:
            log.exception("export failed")
            return self._fail("ذخیره فایل خروجی انجام نشد.", str(exc))
        return self._ok(path=path, name=os.path.basename(path))

    # ------------------------------------------------------------- config
    def get_config(self) -> dict:
        return self._ok(config=load_config())

    def set_config(self, values: dict) -> dict:
        try:
            return self._ok(config=save_config(values or {}))
        except Exception as exc:
            log.exception("config save failed")
            return self._fail("ذخیره تنظیمات انجام نشد.", str(exc))

    def reset(self) -> dict:
        with self._lock:
            self.rows, self.stats = [], {}
        self.pdf_path = self.excel_path = self.brand = ""
        return self._ok()
