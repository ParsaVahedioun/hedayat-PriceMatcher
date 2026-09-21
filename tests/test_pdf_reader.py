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


class CodelessRowTests(unittest.TestCase):
    """Many Iranian price lists (row-numbered catalogues, e.g. خدری/امگا)
    never print a latin model code at all - only a row number, a Persian
    description and a price. Those rows must still become products."""

    def test_a_row_with_a_price_but_no_latin_code_is_still_kept(self):
        rows = rows_of(
            (100.0, 540.0, 560.0, "۱"),
            (100.0, 250.0, 500.0, "المپ ۷ وات ال ای دی اشکی شمعی"),
            (100.0, 100.0, 160.0, "۱٫۸۰۰٫۰۰۰"),
        )
        items = [finalize(p) for p in _products_from_rows(rows, 1, CFG)]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].code, "")
        self.assertEqual(items[0].price, 1800000)
        self.assertEqual(items[0].specs.get("watt"), 7)

    def test_a_bare_row_number_and_price_with_no_description_is_dropped(self):
        rows = rows_of(
            (100.0, 540.0, 560.0, "۱"),
            (100.0, 100.0, 160.0, "۱٫۸۰۰٫۰۰۰"),
        )
        items = _products_from_rows(rows, 1, CFG)
        self.assertEqual(items, [])


class WattColumnTests(unittest.TestCase):
    """Some price lists print a "توان" (wattage) column with the number
    printed bare, on the data rows, with no unit word anywhere near it -
    the unit is only spelled out once, in the header. Position is then
    the only thing telling that number apart from cartons/code digits."""

    def _header(self):
        return [
            (100.0, 300.0, 320.0, "توان"),
            (100.0, 480.0, 520.0, "قیمت"),
            (100.0, 540.0, 580.0, "تومان"),
            (100.0, 550.0, 600.0, "کد"),
        ]

    def test_bare_watt_numbers_are_read_per_row_from_their_column(self):
        rows = rows_of(*(
            self._header() + [
                (150.0, 540.0, 580.0, "BIG2372"),
                (150.0, 460.0, 500.0, "1,600,000"),
                (150.0, 400.0, 430.0, "100"),   # cartons - not in the توان band
                (150.0, 305.0, 315.0, "7"),     # watt - aligned with the header
                (170.0, 540.0, 580.0, "BIG2382"),
                (170.0, 460.0, 500.0, "2,200,000"),
                (170.0, 400.0, 430.0, "100"),
                (170.0, 305.0, 315.0, "12"),
            ]
        ))
        items = {p.code: finalize(p) for p in _products_from_rows(rows, 1, CFG)}
        self.assertEqual(items["BIG2372"].specs.get("watt"), 7)
        self.assertEqual(items["BIG2382"].specs.get("watt"), 12)

    def test_two_numbers_near_the_column_is_left_unresolved(self):
        rows = rows_of(*(
            self._header() + [
                (150.0, 540.0, 580.0, "BIG9999"),
                (150.0, 460.0, 500.0, "1,600,000"),
                (150.0, 308.0, 312.0, "7"),
                (150.0, 298.0, 302.0, "9"),
            ]
        ))
        items = [finalize(p) for p in _products_from_rows(rows, 1, CFG)]
        self.assertIsNone(items[0].specs.get("watt"))

    def test_no_header_seen_means_no_guessing_at_all(self):
        rows = rows_of(
            (150.0, 540.0, 580.0, "BIG1111"),
            (150.0, 460.0, 500.0, "1,600,000"),
            (150.0, 305.0, 315.0, "7"),
        )
        items = [finalize(p) for p in _products_from_rows(rows, 1, CFG)]
        self.assertIsNone(items[0].specs.get("watt"))


class SplitPriceTokenTests(unittest.TestCase):
    """A price is sometimes drawn as several separate word objects - one
    per digit group and one per separator - instead of a single "1,699,000"
    token; on an RTL page those come out in a scrambled-looking word order
    but each is still just one character wide, tightly packed together."""

    def test_a_price_split_into_digit_and_separator_tokens_is_reassembled(self):
        rows = rows_of(
            (100.0, 540.0, 580.0, "AWH09"),
            (100.0, 490.0, 520.0, "9"),
            (100.0, 460.0, 490.0, "وات"),
            (100.0, 430.0, 458.0, "100"),
            (100.0, 400.0, 428.0, "عددي"),
            # the price "1,699,000" as five separate, tightly-packed tokens
            (100.0, 150.0, 158.0, "000"),
            (100.0, 147.0, 150.0, "\u060c"),
            (100.0, 130.0, 147.0, "699"),
            (100.0, 127.0, 130.0, "\u060c"),
            (100.0, 120.0, 127.0, "1"),
        )
        items = [finalize(p) for p in _products_from_rows(rows, 1, CFG)]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].price, 1699000)

    def test_two_genuinely_different_columns_are_never_glued_together(self):
        # "100" (cartons) and the price sit far apart - must not merge into
        # one bogus number even though both are bare digit tokens
        rows = rows_of(
            (100.0, 540.0, 580.0, "AWH09"),
            (100.0, 430.0, 458.0, "100"),
            (100.0, 120.0, 158.0, "1,699,000"),
        )
        items = [finalize(p) for p in _products_from_rows(rows, 1, CFG)]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].price, 1699000)


class CodeDataColumnPairingTests(unittest.TestCase):
    """Some price lists lay a codes column out completely independently of
    its description+price column - the two keep their own even vertical
    rhythm, so a code can sit tens of points away from the row it names,
    far past the usual "typo'd onto the line above" gap tolerance."""

    def test_far_apart_code_and_data_columns_are_still_paired_up(self):
        rows = rows_of(
            # codes column - evenly spaced, unrelated to the data rhythm
            (100.0, 540.0, 580.0, "AWH09"),
            (140.0, 540.0, 580.0, "AWH12"),
            (180.0, 540.0, 580.0, "AWH15"),
            # data column - its own rhythm, offset from the codes by more
            # than the normal same-row gap tolerance (but still the same
            # general table, unlike the far-off footer/title below)
            (118.0, 100.0, 400.0, "لامپ 9 وات 100 عددي 1,699,000"),
            (155.0, 100.0, 400.0, "لامپ 12 وات 100 عددي 2,089,000"),
            (200.0, 100.0, 400.0, "لامپ 15 وات 100 عددي 2,699,000"),
        )
        items = {p.code: finalize(p) for p in _products_from_rows(rows, 1, CFG)}
        self.assertEqual(set(items), {"AWH09", "AWH12", "AWH15"})
        self.assertEqual(items["AWH09"].price, 1699000)
        self.assertEqual(items["AWH12"].price, 2089000)
        self.assertEqual(items["AWH15"].price, 2699000)

    def test_a_page_title_or_footer_does_not_get_pulled_into_the_pairing(self):
        rows = rows_of(
            (10.0, 100.0, 300.0, "1405/06/25"),   # a date stamp, well above the table
            (100.0, 540.0, 580.0, "AWH09"),
            (140.0, 540.0, 580.0, "AWH12"),
            (180.0, 540.0, 580.0, "AWH15"),
            (118.0, 100.0, 400.0, "لامپ 9 وات 100 عددي 1,699,000"),
            (155.0, 100.0, 400.0, "لامپ 12 وات 100 عددي 2,089,000"),
            (200.0, 100.0, 400.0, "لامپ 15 وات 100 عددي 2,699,000"),
            (400.0, 100.0, 400.0, "شركت فلان 09123456789"),  # footer, well below
        )
        items = {p.code: finalize(p) for p in _products_from_rows(rows, 1, CFG) if p.code}
        self.assertEqual(set(items), {"AWH09", "AWH12", "AWH15"})

    def test_two_lone_codes_alone_are_not_treated_as_a_table(self):
        # below the "at least 3 pairs" floor - too easy to trigger by chance
        rows = rows_of(
            (100.0, 540.0, 580.0, "AB01"),
            (140.0, 540.0, 580.0, "AB02"),
            (118.0, 100.0, 400.0, "لامپ 9 وات 100 عددي 1,699,000"),
            (155.0, 100.0, 400.0, "لامپ 12 وات 100 عددي 2,089,000"),
        )
        items = [finalize(p) for p in _products_from_rows(rows, 1, CFG) if p.code]
        self.assertEqual(items, [])


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
