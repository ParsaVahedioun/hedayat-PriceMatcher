"""PriceMatcher - entry point.

    python main.py                       -> desktop window (pywebview)
    python main.py --cli a.pdf b.xlsx    -> headless run, prints a summary
"""
from __future__ import annotations

import argparse
import os
import sys

# make imports work both from source and from a PyInstaller bundle
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.logger import get_logger  # noqa: E402

log = get_logger("main")

WINDOW_TITLE = "Price Matcher"


def ui_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", BASE_DIR), "ui")
    return os.path.join(BASE_DIR, "ui")


def run_gui() -> int:
    try:
        import webview
    except ImportError:
        print("pywebview نصب نیست. اجرا کنید: pip install -r requirements.txt")
        return 1

    from api import Api

    api = Api()
    window = webview.create_window(
        WINDOW_TITLE,
        os.path.join(ui_dir(), "index.html"),
        js_api=api,
        width=1180,
        height=760,
        min_size=(900, 600),
        text_select=True,
    )
    api.window = window
    log.info("starting gui")
    webview.start(debug=os.environ.get("PM_DEBUG") == "1")
    return 0


def run_cli(pdf_path: str, excel_path: str, out_dir: str | None, brand: str = "") -> int:
    from core.errors import AppError
    from core import pipeline
    from core.exporter import export_excel, export_pdf

    def progress(percent: int, message: str) -> None:
        sys.stdout.write(f"\r[{percent:3d}%] {message}   ")
        sys.stdout.flush()

    try:
        result = pipeline.run(pdf_path, excel_path, progress, brand=brand)
    except AppError as exc:
        print("\nخطا:", exc.message)
        log.error("cli error: %s | %s", exc.message, exc.detail)
        return 2

    stats = result["stats"]
    _print_stats(stats)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        rows = [row for row in result["rows"] if row["price"] is not None]
        xlsx = export_excel(rows, os.path.join(out_dir, "result.xlsx"), stats)
        pdf = export_pdf(rows, os.path.join(out_dir, "result.pdf"), stats)
        print("Excel:", xlsx)
        print("PDF  :", pdf)
    return 0


def run_cli_batch(pdf_specs: list[str], excel_path: str, out_dir: str | None) -> int:
    """Headless run over several PDFs at once (see --pdf below).

    Each `pdf_specs` entry is "path" or "path:brand". Every PDF is read and
    matched one by one, and a row already priced by an earlier PDF is left
    untouched by a later one - see `pipeline.run_batch`.
    """
    from core.errors import AppError
    from core import pipeline
    from core.exporter import export_excel, export_pdf

    entries = []
    for spec in pdf_specs:
        path, _, brand = spec.partition(":")
        entries.append({"path": path, "brand": brand, "name": os.path.basename(path)})

    def progress(percent: int, message: str) -> None:
        sys.stdout.write(f"\r[{percent:3d}%] {message}   ")
        sys.stdout.flush()

    try:
        result = pipeline.run_batch(entries, excel_path, progress)
    except AppError as exc:
        print("\nخطا:", exc.message)
        log.error("cli batch error: %s | %s", exc.message, exc.detail)
        return 2

    stats = result["stats"]
    print("\n")
    for f in stats.get("files", []):
        status = "OK" if f.get("ok") else "FAILED: " + f.get("error", "")
        print(f"  - {f['name']} (brand={f.get('brand') or '-'}): "
              f"read={f.get('pdf_rows', 0)} priced={f.get('priced', 0)}  [{status}]")
    _print_stats(stats)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        rows = [row for row in result["rows"] if row["price"] is not None]
        xlsx = export_excel(rows, os.path.join(out_dir, "result.xlsx"), stats)
        pdf = export_pdf(rows, os.path.join(out_dir, "result.pdf"), stats)
        print("Excel:", xlsx)
        print("PDF  :", pdf)
    return 0


def _print_stats(stats: dict) -> None:
    print("\n")
    print(f"Inventory rows : {stats['total']}")
    print(f"Price rows read: {stats['pdf_rows']}")
    print(f"Priced         : {stats['priced']}")
    print(f"  exact        : {stats['exact']}")
    print(f"  confident    : {stats['high']}")
    print(f"  review       : {stats['review']}")
    print(f"Not found      : {stats['not_found']}")
    print(f"Elapsed        : {stats['elapsed']}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="PDF price list + Excel inventory matcher")
    parser.add_argument("--cli", nargs=2, metavar=("PDF", "EXCEL"), help="run without a window (single PDF)")
    parser.add_argument("--out", metavar="DIR", help="export results to this folder (cli mode)")
    parser.add_argument("--brand", default="", help="brand name of the PDF price list (--cli mode)")
    parser.add_argument(
        "--pdf", action="append", metavar="PATH[:BRAND]", default=None,
        help="a PDF price list to process, optionally with its brand after a colon "
             "(repeatable - one per file); use together with --excel to run several "
             "PDFs against the same inventory in one pass",
    )
    parser.add_argument("--excel", metavar="EXCEL", help="inventory file for --pdf batch mode")
    args = parser.parse_args()

    if args.pdf:
        if not args.excel:
            print("--excel لازم است وقتی از --pdf استفاده می‌شود.")
            return 2
        return run_cli_batch(args.pdf, args.excel, args.out)
    if args.cli:
        return run_cli(args.cli[0], args.cli[1], args.out, args.brand)
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
