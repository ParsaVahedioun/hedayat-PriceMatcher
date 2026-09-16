"""Application errors.

Every error shown to the user goes through one of these, so raw Python
tracebacks never reach the UI (they only go to logs/app.log).
"""
from __future__ import annotations


class AppError(Exception):
    """Base class: `message` is already a clean Persian sentence."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


class PdfError(AppError):
    pass


class ExcelError(AppError):
    pass


class ExportError(AppError):
    pass


MSG_PDF_UNREADABLE = "فایل PDF قابل خواندن نیست."
MSG_EXCEL_UNREADABLE = "فایل Excel قابل خواندن نیست."
MSG_EXCEL_COLUMNS = "ستون کد کالا / نام کالا / موجودی پیدا نشد."
MSG_PDF_NO_PRODUCTS = (
    "هیچ کالایی از PDF استخراج نشد.\nممکن است PDF اسکن‌شده باشد."
)
MSG_EXCEL_EMPTY = "هیچ ردیفی در فایل Excel پیدا نشد."
