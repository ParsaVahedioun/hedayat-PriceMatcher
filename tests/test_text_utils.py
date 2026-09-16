"""Text layer: the part that decides whether Persian survives extraction."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.text_utils import (  # noqa: E402
    code_family, dense, normalize_code, normalize_text,
    shape_to_plain, split_latin_persian, to_english_digits,
)


class ShapingTests(unittest.TestCase):
    def test_presentation_forms_fold_back_to_plain_letters(self):
        self.assertEqual(shape_to_plain("\ufee3\ufeec\ufe98\ufe8e\ufe91\ufbfd"), "مهتابی")

    def test_broken_subset_font_glyphs_are_repaired(self):
        # the exact breakage the Schiele price list has: ب, ی, پ, ن, ت mapped
        # onto latin code points by the embedded subset font
        self.assertEqual(shape_to_plain("\ufee3\ufeec\ufe98\ufe8e\u01ac\ufbfd"), "مهتابی")
        self.assertEqual(shape_to_plain("\ufee3\u01ae\ufeae"), "مپر")
        self.assertEqual(
            shape_to_plain("\ufee3\ufbff\u01d7\ufbff\ufe8e\ufe97\ufeee"), "مینیاتو"
        )

    def test_persian_digits_become_english(self):
        self.assertEqual(to_english_digits("۱۴۱٬۰۰۰"), "141٬000")

    def test_latin_glued_to_persian_is_split(self):
        self.assertEqual(split_latin_persian("وات15"), "وات 15")
        self.assertTrue(split_latin_persian("ردار2,200,000").startswith("ردار 2"))


class NormalizationTests(unittest.TestCase):
    def test_dense_ignores_the_word_breaks_a_pdf_invents(self):
        # "مد ل تو ان" is how a PDF writes "مدل توان"
        self.assertIn("توان", dense("مد ل تو ان ر نگ"))

    def test_normalize_code_strips_punctuation_and_uppercases(self):
        self.assertEqual(normalize_code("SCTRW/B30"), "SCTRWB30")

    def test_code_family_is_the_leading_letter_run(self):
        self.assertEqual(code_family("SCAP-42-S2"), "SCAP")
        self.assertEqual(code_family("VS6-1C02"), "VS")

    def test_zwnj_and_arabic_letters_are_unified(self):
        self.assertEqual(
            normalize_text("کلید\u200cمینیاتوری"), normalize_text("كليد مينياتوري")
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
