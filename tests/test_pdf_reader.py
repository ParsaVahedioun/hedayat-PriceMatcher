"""Row reconstruction from word geometry."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pdf_reader import _products_from_rows, build_rows, finalize  # noqa: E402

CFG = {"min_valid_price": 1000, "max_valid_price": 10 ** 10, "pdf_orphan_row_gap": 12}


def rows_of(*words):
    """Build visual rows from (y, x0, x1, text) tuples, given in any order."""
    return build_rows(list(words))


class RowGroupingTests(unittest.TestCase):
    def test_words_group_into_rows_by_vertical_centre(self):
        rows = rows_of(
            (100.0, 500.0, 540.0, "SCAP-7"),
            (101.0, 120.0, 160.0, "141٫000"),
            (130.0, 500.0, 540.0, "SCAP-9"),
        )
        self.assertEqual(len(rows), 2)

    def test_words_inside_a_row_come_out_right_to_left(self):
        rows = rows_of(
            (100.0, 120.0, 160.0, "141٫000"),
            (100.0, 500.0, 540.0, "SCAP-7"),
        )
        self.assertEqual(rows[0]["words"][0][2], "SCAP-7")


class ProductRowTests(unittest.TestCase):
    def test_a_row_with_a_code_and_a_price_becomes_a_product(self):
        rows = rows_of(
            (100.0, 547.0, 580.0, "SCAP-12"),
            (100.0, 490.0, 530.0, "وات۱۲"),
            (100.0, 115.0, 155.0, "۲۹۷٫۰۰۰"),
        )
        items = [finalize(p) for p in _products_from_rows(rows, 3, CFG)]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].code, "SCAP-12")
        self.assertEqual(items[0].price, 297000)
        self.assertEqual(items[0].specs["watt"], 12)

    def test_the_leftmost_number_wins_because_price_is_the_outer_column(self):
        # 1200 is a dimension sitting in the middle of the row, not the price
        rows = rows_of(
            (100.0, 547.0, 590.0, "SCLFT1-80"),
            (100.0, 300.0, 340.0, "۱۲۰۰"),
            (100.0, 115.0, 160.0, "۱٫۶۴۰٫۰۰۰"),
        )
        self.assertEqual(_products_from_rows(rows, 6, CFG)[0].price, 1640000)

    def test_a_code_continued_on_the_next_line_is_glued_back_on(self):
        rows = rows_of(
            (215.0, 547.0, 590.0, "SCWLS-2835"),
            (215.0, 115.0, 155.0, "۱۳۲٫۰۰۰"),
            (224.0, 547.0, 566.0, "120"),
        )
        self.assertEqual(_products_from_rows(rows, 10, CFG)[0].code, "SCWLS-2835-120")

    def test_an_english_note_printed_over_a_row_is_not_glued_onto_the_code(self):
        rows = rows_of(
            (100.0, 547.0, 590.0, "SCAC-42"),
            (100.0, 115.0, 160.0, "۱٫۶۴۵٫۰۰۰"),
            (108.0, 32.0, 64.0, "Flicker"),
        )
        self.assertEqual(_products_from_rows(rows, 3, CFG)[0].code, "SCAC-42")

    def test_a_decorative_note_does_not_discard_the_product_row(self):
        # "+IC Driver" is typeset on top of the SCFM-36 row in the real file
        rows = rows_of(
            (654.0, 547.0, 590.0, "SCFM-36"),
            (654.0, 490.0, 520.0, "وات۳۶"),
            (654.0, 115.0, 160.0, "۶۴۷٫۰۰۰"),
            (654.0, 32.0, 60.0, "Driver"),
        )
        items = _products_from_rows(rows, 5, CFG)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].price, 647000)

    def test_a_price_typeset_on_its_own_line_is_pulled_into_the_row(self):
        rows = rows_of(
            (240.0, 547.0, 600.0, "VSDOBE-24"),
            (240.0, 490.0, 520.0, "وات۲۴"),
            (245.0, 115.0, 160.0, "۹۵۰٫۰۰۰"),
        )
        self.assertEqual(_products_from_rows(rows, 4, CFG)[0].price, 950000)

    def test_a_coming_soon_row_yields_no_product(self):
        rows = rows_of(
            (784.0, 547.0, 590.0, "SCFS-45"),
            (784.0, 400.0, 440.0, "وات۴۵"),
            (784.0, 115.0, 150.0, "بزودی"),
        )
        self.assertEqual(_products_from_rows(rows, 5, CFG), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
