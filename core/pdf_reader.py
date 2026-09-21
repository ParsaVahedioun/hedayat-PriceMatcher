"""PDF price-list reader.

Persian price lists are laid out as visual tables that carry no table
structure at all: `find_tables()` returns nothing and the plain text dump
comes out scrambled, because the producing tool writes every glyph cluster as
its own positioned run, right-to-left, in arbitrary order.

So the reader works on geometry instead of on text:

    1. take every word with its bounding box
    2. group words into visual rows by their vertical centre
    3. inside a row, sort right-to-left (Persian reading order)
    4. a row is a product when it has a model code and a price
    5. the nearest table title above it becomes the row's section

Only if a page carries (almost) no text layer at all is OCR used, as before.
"""
from __future__ import annotations

import os
import re
from typing import Callable

from core.attributes import extract_specs
from core.errors import MSG_PDF_NO_PRODUCTS, MSG_PDF_UNREADABLE, PdfError
from models.product import PriceItem
from utils.config import load_config
from utils.logger import get_logger
from utils.text_utils import (
    clean_spaces,
    dense,
    code_family,
    normalize_code,
    normalize_text,
    shape_to_plain,
    to_english_digits,
)

log = get_logger("pdf")

# A model code: starts with 2+ latin letters, then letters/digits/-/_/ and
# optionally a parenthesised range, e.g. SCAP-42-S2, VS6-1C(6-32), SCTRW/B20.
_CODE_RE = re.compile(r"^[A-Za-z]{2,}[A-Za-z0-9]*(?:[\-/.][A-Za-z0-9()\-]+)*$")
_CODE_TAIL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-/()]*$")
# A price: at least four digits, usually with a thousands separator. Three
# different "Arabic comma" look-alikes show up as that separator depending
# on which tool produced the PDF: \u066c (the actual Arabic thousands
# separator), \u060c (plain Arabic comma, reused for the same purpose by
# many invoicing tools) and the ordinary ",".
_PRICE_RE = re.compile(r"\d{1,3}(?:[,.\u066c\u060c]\d{3})+|\d{4,}")
_LATIN_ONLY = re.compile(r"^[A-Za-z0-9\-/()*.:+]+$")

# rows whose text is one of these are titles/footers, never products
_NOISE_RE = re.compile(
    r"(pricelist|page\s*no|بازگشت به فهرست|لیست قیمت|شماره صفحه|"
    r"flicker|body material|heat sink|driver|new product)",
    re.IGNORECASE,
)
# words a column-header row is made of; two hits are enough because the
# comparison runs on the space-free form, where a false positive is unlikely
_HEADER_WORDS = (
    "مدل", "قیمت", "تومان", "تعداد در کارتن", "تعداد در بسته", "توان",
    "رنگ نور", "رنگ بدنه", "سایز بیرونی", "سایز برش", "فرم بدنه", "توضیحات",
    "نوع قطعه", "نوع درایور", "نوع سنسور", "نوع چراغ", "نوع منبع تغذیه",
    "سری ریسه", "متراژ در کارتن", "قدرت قطع اتصال کوتاه", "جریان نشتی",
    "زاویه پوشش", "ارتفاع نصب", "محدوده آشکار سازی", "درجه حفاظتی", "تراکم",
    "زاویه پرتاب نور", "سایز چسب",
)

# "coming soon" - the row exists but has no price yet
_NO_PRICE_WORDS = ("بزودی", "به زودی", "زودی")


# ------------------------------------------------------------------ backends
def _pymupdf():
    """PyMuPDF under either of its module names.

    The package renamed itself from `fitz` to `pymupdf`; importing the old
    name still works but prints a deprecation warning on every run.
    """
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        import fitz

        return fitz


def _open_backend(path: str):
    """Return (kind, document). kind is 'fitz' or 'plumber'."""
    try:
        fitz = _pymupdf()

        return "fitz", fitz.open(path)
    except ImportError:
        pass
    except Exception as exc:
        raise PdfError(MSG_PDF_UNREADABLE, str(exc)) from exc
    try:
        import pdfplumber

        return "plumber", pdfplumber.open(path)
    except ImportError as exc:  # pragma: no cover
        raise PdfError("کتابخانه PyMuPDF نصب نیست.", str(exc)) from exc
    except Exception as exc:
        raise PdfError(MSG_PDF_UNREADABLE, str(exc)) from exc


def _page_count(kind, doc) -> int:
    return doc.page_count if kind == "fitz" else len(doc.pages)


def _page_words(kind, doc, i: int) -> list[tuple[float, float, float, str]]:
    """[(y_center, x0, x1, text), ...] for one page."""
    out: list[tuple[float, float, float, str]] = []
    if kind == "fitz":
        for word in doc.load_page(i).get_text("words"):
            x0, y0, x1, y1, text = word[0], word[1], word[2], word[3], word[4]
            out.append(((y0 + y1) / 2.0, x0, x1, shape_to_plain(text)))
    else:
        for word in doc.pages[i].extract_words() or []:
            y0, y1 = float(word["top"]), float(word["bottom"])
            out.append((
                (y0 + y1) / 2.0, float(word["x0"]), float(word["x1"]),
                shape_to_plain(word["text"]),
            ))
    return out


def _page_text(kind, doc, i: int) -> str:
    if kind == "fitz":
        return doc.load_page(i).get_text("text") or ""
    return doc.pages[i].extract_text() or ""


def _close(kind, doc):
    try:
        doc.close()
    except Exception:
        pass


# --------------------------------------------------------------- row layout
def build_rows(words, tolerance: float = 3.5) -> list[dict]:
    """Group words into visual rows, ordered top to bottom.

    Each row: {"y", "x_min", "words": [(x0, x1, text), ...]} with the words
    already sorted right-to-left, which is Persian reading order.
    """
    ordered = sorted(words, key=lambda w: (w[0], -w[1]))
    rows: list[dict] = []
    current: list[tuple[float, float, float, str]] = []
    anchor: float | None = None

    for word in ordered:
        if anchor is None or abs(word[0] - anchor) <= tolerance:
            if anchor is None:
                anchor = word[0]
            current.append(word)
        else:
            rows.append(_finish_row(current))
            current, anchor = [word], word[0]
    if current:
        rows.append(_finish_row(current))
    return rows


def _finish_row(words) -> dict:
    ordered = sorted(words, key=lambda w: -w[1])
    return {
        "y": sum(w[0] for w in words) / len(words),
        "x_min": min(w[1] for w in words),
        "words": [(w[1], w[2], w[3]) for w in ordered],
        "text": clean_spaces(" ".join(w[3] for w in ordered)),
    }


# ---------------------------------------------------------- row -> product
def _row_code(row: dict) -> tuple[str, int]:
    """Model code of a row plus the index of the last word it consumed.

    The code sits in the right-most column, but is sometimes split over two
    words ("VSDOBE-24" + "P"), so adjacent latin-only words are joined.
    """
    words = row["words"]
    if not words:
        return "", -1
    start = 0
    parts: list[str] = []
    first = words[0][2]
    # a leading one-letter suffix such as "P" belongs to the code after it
    if len(first) <= 2 and _LATIN_ONLY.match(first) and len(words) > 1 \
            and _CODE_RE.match(words[1][2]):
        parts.append(first)
        start = 1
    candidate = words[start][2]
    if not _CODE_RE.match(candidate):
        return "", -1
    parts.insert(0, candidate)
    end = start
    # glue a trailing fragment written as its own word, e.g. "(6-32)"
    while end + 1 < len(words):
        nxt = words[end + 1][2]
        if nxt.startswith("(") and nxt.endswith(")") and _CODE_TAIL_RE.match(nxt.strip("()")):
            parts.append(nxt)
            end += 1
        else:
            break
    return "-".join(p.strip("-") for p in parts if p), end


def _row_price(row: dict, min_price: float, max_price: float) -> float | None:
    """The price of a row: the left-most number that looks like money.

    Every price list puts the price in the outermost column; on an RTL page
    that is the smallest x. Picking by position rather than by magnitude is
    what keeps "4500K" or a 1200 mm dimension from being read as a price.

    Some PDF exporters draw a thousands-separated number as several
    independent text objects instead of one - each digit group and each
    separator gets its own word ("1", "،", "699", "،", "000") - so besides
    checking each word alone, adjacent digit/separator-only words are also
    glued back together (by how close together they sit) before the price
    pattern is tried again on the reassembled text.
    """
    best: tuple[float, float] | None = None   # (x, value)

    def consider(x0: float, plain: str) -> None:
        nonlocal best
        for match in _PRICE_RE.finditer(plain):
            raw = re.sub(r"[,.\s]", "", match.group(0))
            if not raw.isdigit():
                continue
            value = float(raw)
            if not (min_price <= value <= max_price):
                continue
            if best is None or x0 < best[0]:
                best = (x0, value)

    for x0, _x1, text in row["words"]:
        consider(x0, to_english_digits(text).replace("\u066c", ",").replace("\u066b", ",").replace("\u060c", ","))

    run_x0 = 0.0
    run_text = ""
    prev_end: float | None = None
    for x0, x1, text in sorted(row["words"], key=lambda w: w[0]):
        plain = to_english_digits(text).replace("\u066c", ",").replace("\u066b", ",").replace("\u060c", ",")
        is_piece = bool(re.fullmatch(r"[\d,.]+", plain))
        if is_piece and prev_end is not None and x0 - prev_end <= 8:
            run_text += plain
        else:
            if run_text:
                consider(run_x0, run_text)
            run_x0, run_text = x0, (plain if is_piece else "")
        prev_end = x1 if is_piece else None
    if run_text:
        consider(run_x0, run_text)

    return best[1] if best else None


def _is_header_row(text: str) -> bool:
    packed = dense(text)
    return sum(1 for word in _HEADER_WORDS if dense(word) in packed) >= 2


def _is_noise(text: str) -> bool:
    if _NOISE_RE.search(text):
        return True
    return _is_header_row(text)


def _fragment_of(row: dict) -> str:
    """The code continuation a row starts with, or "".

    Multi-line model codes are typeset as a second line under the first
    ("SCWLS-2835" / "120", "SCLINEPRO" / "12V-120"); on its own such a line
    is meaningless, so it is glued back onto the product row above it.
    """
    words = row["words"]
    if not words:
        return ""
    head = words[0][2].strip()
    if not head or len(head) > 14 or not _LATIN_ONLY.match(head):
        return ""
    if not any(char.isdigit() for char in head):
        # a plain English note such as "Flicker Free" is not a code
        return ""
    if len(words) == 1:
        return head
    # inside a longer row only an unmistakable code shape is accepted
    return head if any(char.isalpha() for char in head) else ""


def _latin_part(text: str) -> str:
    return clean_spaces(" ".join(
        word for word in text.split(" ") if _LATIN_ONLY.match(word)
    ))


def _persian_part(text: str) -> str:
    return clean_spaces(" ".join(
        word for word in text.split(" ") if not _LATIN_ONLY.match(word)
    ))


def _is_section_title(row: dict, packed: str) -> bool:
    """A table caption: a headline with no code column and no price."""
    if len(packed) < 6 or _is_noise(row["text"]):
        return False
    persian = _persian_part(row["text"])
    return len(dense(persian)) >= 5


def _header_column_x(row: dict, header_word: str) -> tuple[float, float] | None:
    """x0, x1 of a column header cell matching `header_word` exactly."""
    target = dense(header_word)
    for x0, x1, word_text in row["words"]:
        if dense(word_text) == target:
            return (x0, x1)
    return None


def _bare_number_in_column(row: dict, column: tuple[float, float], used_last: int) -> str:
    """A short standalone integer positioned under a known column header.

    Some price lists print a numeric column (almost always "توان" -
    wattage) with no unit word next to the value at all; the unit only
    appears once, in the header, which extraction never keeps around row
    by row. Position is then the only thing telling that number apart from
    the row's other bare numbers (carton count, a code's own digits) - a
    row with more than one candidate in that column band is left alone
    rather than guessed at.
    """
    lo, hi = column
    center = (lo + hi) / 2.0
    tolerance = 22.0
    hits: list[str] = []
    for word_index, (x0, x1, word_text) in enumerate(row["words"]):
        if word_index <= used_last:
            continue  # already consumed as (part of) the model code
        plain = to_english_digits(word_text)
        if not plain.isdigit() or not (1 <= len(plain) <= 3):
            continue
        if abs((x0 + x1) / 2.0 - center) <= tolerance:
            hits.append(plain)
    return hits[0] if len(hits) == 1 else ""


def _pair_columns_sequentially(scanned: list[dict]) -> list[tuple[dict, dict]]:
    """Pair a page's lone-code rows with its lone-price rows, in order.

    A handful of price lists lay the model codes out as their own column,
    typeset completely independently from the description+price column
    next to it - each column keeps its own even vertical rhythm, so a code
    and the row it actually belongs to can end up dozens of points apart
    vertically, far past any reasonable "typo'd onto the line above" gap.
    When a page has exactly as many "just a code, nothing else" rows as it
    has "a price, no code at all" rows, pairing them by top-to-bottom order
    is far more reliable than picking whichever one happens to sit closest.
    """
    codes: list[dict] = []
    data: list[dict] = []
    for entry in scanned:
        if entry["used"]:
            continue
        text = entry["row"]["text"]
        if not text or _is_noise(text):
            continue
        code, price, words = entry["code"], entry["price"], entry["row"]["words"]
        if code and price is None and entry["last"] == len(words) - 1 and any(ch.isdigit() for ch in code):
            # a lone model code and nothing else on its line - real model
            # codes almost always carry a digit; a bare English annotation
            # word ("SMD", "Flicker Free") normally does not
            codes.append(entry)
        elif not code and price is not None:
            data.append(entry)
    if len(codes) < 3:
        return []
    # a genuine data row for this table sits roughly in the same vertical
    # span as the code column itself; a page title, a date stamp, or a
    # footer address further up or down the page is not part of the table
    # even though it too happens to have "no code, something priceable"
    lo = min(e["row"]["y"] for e in codes) - 30
    hi = max(e["row"]["y"] for e in codes) + 30
    data = [entry for entry in data if lo <= entry["row"]["y"] <= hi]
    if len(codes) != len(data):
        return []
    return list(zip(codes, data))


def _products_from_rows(rows: list[dict], page_no: int, cfg: dict) -> list[PriceItem]:
    """Turn the visual rows of one page into price-list products."""
    min_price = float(cfg.get("min_valid_price", 0))
    max_price = float(cfg.get("max_valid_price", float("inf")))
    gap = float(cfg.get("pdf_orphan_row_gap", 12))

    scanned = []
    for row in rows:
        code, last = _row_code(row)
        scanned.append({
            "row": row,
            "code": code,
            "last": last,
            "price": _row_price(row, min_price, max_price),
            "used": False,
        })

    section_fa = section_en = ""
    watt_col: tuple[float, float] | None = None
    products: list[PriceItem] = []

    for code_entry, data_entry in _pair_columns_sequentially(scanned):
        code_entry["used"] = True
        data_entry["used"] = True
        products.append(PriceItem(
            code=code_entry["code"],
            price=data_entry["price"],
            text=clean_spaces(data_entry["row"]["text"]),
            page=page_no,
        ))

    for index, entry in enumerate(scanned):
        if entry["used"]:
            continue
        row = entry["row"]
        text = row["text"]
        if not text:
            continue

        if _is_header_row(text):
            # column headers repeat at the top of every page in these price
            # lists; remember where the "توان" (wattage) column sits so the
            # data rows below - which carry no unit word at all - can still
            # be tagged with it further down.
            found = _header_column_x(row, "توان")
            if found:
                watt_col = found

        code, price = entry["code"], entry["price"]
        # A decorative note ("+IC Driver", "Flicker Free") is often typeset
        # on top of a product row. Noise only disqualifies a row that has
        # nothing else going for it - a row carrying both a model code and a
        # price is a product whatever else was printed over it.
        if _is_noise(text) and not (code and price is not None):
            continue

        if not code:
            if price is None and _is_section_title(row, dense(text)):
                section_fa = _persian_part(text)
                section_en = _latin_part(text)
            elif price is not None:
                # a data row whose code was typeset on the line above it
                borrowed = _borrow_code(scanned, index, gap)
                if borrowed:
                    code = borrowed
                elif len(re.sub(r"[0-9]", "", dense(_persian_part(text)))) >= 4:
                    # no latin model code anywhere nearby - many Iranian
                    # price lists (numbered "ردیف" catalogues such as
                    # Khadari/Omidnoor or Omega) never print one at all,
                    # identifying a product only by its Persian description
                    # and a row number that repeats on every page. Keep the
                    # row as a codeless product rather than dropping it: the
                    # matcher already scores a codeless price row purely on
                    # spec/text agreement (see Matcher.code_score).
                    code = ""
                else:
                    continue
            else:
                continue

        if price is None:
            price = _pull_price(scanned, index, gap)
        if price is None:
            # a code with no price is a picture caption or a "coming soon" row
            continue

        body = clean_spaces(" ".join(w[2] for w in row["words"][entry["last"] + 1:]))
        if watt_col is not None:
            watt_value = _bare_number_in_column(row, watt_col, entry["last"])
            if watt_value:
                # makes the value a genuine "N وات" for extract_specs to pick
                # up as a real (hard) watt spec, not just weak bare-number
                # evidence - the column position already told us what it is
                body = clean_spaces(body + " " + watt_value + " وات")
        entry["used"] = True
        item = PriceItem(
            code=code + _trailing_fragment(scanned, index, gap) if code else "",
            price=price,
            text=body,
            section_fa=section_fa,
            section_en=section_en,
            page=page_no,
        )
        products.append(item)
    return products


def _neighbours(scanned, index, gap):
    """Indices of the rows immediately above/below, within `gap` points."""
    base = scanned[index]["row"]["y"]
    for offset in (1, -1, 2, -2):
        other = index + offset
        if 0 <= other < len(scanned) and abs(scanned[other]["row"]["y"] - base) <= gap:
            yield other


def _pull_price(scanned, index, gap) -> float | None:
    """Some prices are typeset on their own line, slightly off the row."""
    for other in _neighbours(scanned, index, gap):
        entry = scanned[other]
        if entry["used"] or entry["code"] or entry["price"] is None:
            continue
        entry["used"] = True
        return entry["price"]
    return None


def _borrow_code(scanned, index, gap) -> str:
    """Take the code from an adjacent caption-only row (e.g. "VSSILVER")."""
    for other in _neighbours(scanned, index, gap):
        entry = scanned[other]
        if entry["used"] or not entry["code"] or entry["price"] is not None:
            continue
        entry["used"] = True
        return entry["code"]
    return ""


def _trailing_fragment(scanned, index, gap) -> str:
    """Glue the continuation line of a two-line model code, once."""
    for other in _neighbours(scanned, index, gap):
        entry = scanned[other]
        if entry["used"] or entry["price"] is not None:
            continue
        alone = len(entry["row"]["words"]) == 1
        # "SLIM-288" on its own line parses as a model code, but a code with
        # no price and nothing else on the line is a continuation, not a row
        if entry["code"] and not alone:
            continue
        fragment = _fragment_of(entry["row"])
        if fragment:
            if alone:
                entry["used"] = True
            return "-" + fragment
    return ""


# ---------------------------------------------------------------------- OCR
def _ocr_page(kind, doc, i: int, cfg: dict) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        log.warning("OCR requested but pytesseract/Pillow not installed")
        return ""
    try:
        import io

        dpi = int(cfg.get("ocr_dpi", 200))
        if kind == "fitz":
            fitz = _pymupdf()

            page = doc.load_page(i)
            zoom = dpi / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
        else:
            image = doc.pages[i].to_image(resolution=dpi).original.convert("L")
        text = pytesseract.image_to_string(image, lang=cfg.get("ocr_language", "fas+eng"))
        image.close()
        return text or ""
    except Exception as exc:
        log.warning("OCR failed on page %d: %s", i, exc)
        return ""


def _products_from_ocr_text(text: str, page_no: int, cfg: dict) -> list[PriceItem]:
    """Fallback for image-only pages: one line = one row, no geometry."""
    fake_rows = []
    for line in text.splitlines():
        line = clean_spaces(shape_to_plain(line))
        if not line:
            continue
        words = line.split(" ")
        # OCR gives no coordinates; assume the line is already in reading order
        fake_rows.append({
            "y": 0.0, "x_min": 0.0, "text": line,
            "words": [(float(i), float(i) + 1, w) for i, w in enumerate(words)],
        })
    return _products_from_rows(fake_rows, page_no, cfg)


# -------------------------------------------------------------------- main
def finalize(item: PriceItem) -> PriceItem:
    """Fill the derived keys of a price row."""
    item.code_key = normalize_code(item.code)
    item.family = code_family(item.code)
    item.context = clean_spaces(
        normalize_text(item.section_fa) + " " + normalize_text(item.text)
    )
    item.specs = extract_specs(
        " ".join([item.code, item.section_fa, item.section_en, item.text])
    )
    _add_code_hints(item)
    item.tokens = tuple(t for t in item.context.split(" ") if t)
    return item


_CODE_NUMBER = re.compile(r"(\d{1,4})(?!.*\d)")


def _add_code_hints(item: PriceItem) -> None:
    """The rating implied by the model code, when the row does not spell it out.

    A price list names its products after the number that identifies them:
    "SCFS-30-P" is the 30 W version, "SCWLC-SLIM-288" the 288-per-metre one.
    Some rows are typeset so badly that the "۳۰ وات" cell cannot be parsed at
    all, and then the code is the only place the number survives.

    Which rating it is follows from the table the row sits in, so the column
    heading decides. A hint is kept apart from a real value and only ever
    supports a match - it never vetoes one, because the convention is a
    convention, not a guarantee.
    """
    match = _CODE_NUMBER.search(item.code)
    if not match:
        return
    value = float(match.group(1))
    if not 1 <= value <= 1000:
        return
    haystack = item.text + " " + item.section_fa
    if "تراکم" in haystack and item.specs.get("density") is None:
        item.specs["density_hint"] = value
    elif "وات" in haystack and item.specs.get("watt") is None:
        item.specs["watt_hint"] = value


def is_scanned(path: str, cfg: dict | None = None) -> bool:
    """True if the document looks image-based (no real text layer)."""
    cfg = cfg or load_config()
    kind, doc = _open_backend(path)
    try:
        limit = min(_page_count(kind, doc), 5)
        chars = sum(len((_page_text(kind, doc, i) or "").strip()) for i in range(limit))
        return chars < int(cfg.get("scanned_char_threshold", 40)) * max(1, limit)
    finally:
        _close(kind, doc)


def read_pdf(
    path: str,
    config: dict | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[PriceItem]:
    cfg = config or load_config()
    if not path or not os.path.isfile(path):
        raise PdfError(MSG_PDF_UNREADABLE, f"file not found: {path}")

    kind, doc = _open_backend(path)
    products: list[PriceItem] = []
    ocr_pages = 0
    try:
        pages = _page_count(kind, doc)
        if pages == 0:
            raise PdfError(MSG_PDF_UNREADABLE, "0 pages")
        char_threshold = int(cfg.get("scanned_char_threshold", 40))
        tolerance = float(cfg.get("pdf_row_tolerance", 3.5))

        for i in range(pages):
            words = _page_words(kind, doc, i)
            characters = sum(len(w[3].strip()) for w in words)
            if characters >= char_threshold:
                rows = build_rows(words, tolerance)
                products.extend(_products_from_rows(rows, i + 1, cfg))
            elif cfg.get("ocr_enabled", True):
                ocr_pages += 1
                products.extend(
                    _products_from_ocr_text(_ocr_page(kind, doc, i, cfg), i + 1, cfg)
                )
            if progress:
                progress(i + 1, pages)
    finally:
        _close(kind, doc)

    products = [finalize(p) for p in products]
    if not products:
        raise PdfError(MSG_PDF_NO_PRODUCTS, f"backend={kind}, ocr_pages={ocr_pages}")
    log.info("pdf: %d rows from %s (ocr pages: %d)",
             len(products), os.path.basename(path), ocr_pages)
    return products
