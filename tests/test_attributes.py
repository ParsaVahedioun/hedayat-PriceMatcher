"""Attribute extraction: the numbers that decide which row is which."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.attributes import (  # noqa: E402
    detect_brand, expand_synonyms, extract_codes, extract_specs,
)


class SpecTests(unittest.TestCase):
    def test_watt_is_found_in_an_inventory_name(self):
        specs = extract_specs("پنل SMD توکار آ پلاست 9 وات گرد مهتابی شیله")
        self.assertEqual(specs["watt"], 9)

    def test_watt_is_found_when_the_pdf_glues_the_unit_before_the_number(self):
        self.assertEqual(extract_specs("وات۱۲ آفتابی ، مهتابی")["watt"], 12)

    def test_amp_survives_a_word_the_pdf_split_in_half(self):
        # the price list writes "آ مپر" with a space inside the word
        self.assertEqual(extract_specs("کلید مینیاتوری تک پل - ۲۵ آ مپر")["amp"], 25)

    def test_an_amp_range_is_kept_as_a_range(self):
        specs = extract_specs("کلید مینیاتوری تک پل - ۶ تا ۳۲ آمپر")
        self.assertEqual(specs["amp_range"], (6.0, 32.0))

    def test_centimetres_are_converted_to_millimetres(self):
        self.assertIn(600.0, extract_specs("براکت 40 وات 60 سانتی")["mm"])

    def test_a_number_inside_a_model_code_is_not_a_rating(self):
        # "SC40A" must not be read as 40 amps
        self.assertIsNone(extract_specs("سنسور هالوژنی SC40A")\
                          .get("amp"))


class CodeAndBrandTests(unittest.TestCase):
    def test_model_codes_are_read_from_the_name(self):
        self.assertEqual(
            extract_codes("پنل SMD توکار آ پلاست 7 وات شیله (SCAP)"), ["SCAP"]
        )
        self.assertEqual(extract_codes("چراغ ریلی 30 وات شیله (SCTRW/B)"), ["SCTRWB"])

    def test_spec_words_are_not_mistaken_for_model_codes(self):
        self.assertEqual(extract_codes("لامپ LED حبابی 9 وات E27 مهتابی"), [])

    def test_brand_detection(self):
        self.assertEqual(detect_brand("چسب برق ویسنا"), "ویسنا")
        self.assertEqual(detect_brand("چسب برق شوان"), "")

    def test_brand_detection_ignores_the_space_inside_a_compound_name(self):
        # "امیدنور" and "امید نور" are the same brand - Persian PDFs/Excel
        # sheets are never consistent about the space between the two halves
        self.assertEqual(detect_brand("لامپ امیدنور 9 وات", {"امید نور": ()}), "امید نور")
        self.assertEqual(detect_brand("لامپ امید نور 9 وات", {"امیدنور": ()}), "امیدنور")


class VocabularyTests(unittest.TestCase):
    def test_single_phase_is_expanded_to_the_pole_wording_of_the_price_list(self):
        self.assertIn("تک پل", expand_synonyms("کلید مینیاتوری تک فاز 16 آمپر ویسنا"))

    def test_a_single_phase_rccb_is_a_two_pole_device(self):
        self.assertIn("دو پل", expand_synonyms("محافظ جان تک فاز 25 آمپر ویسنا"))

    def test_a_three_phase_rccb_is_a_four_pole_device(self):
        self.assertIn("چهار پل", expand_synonyms("محافظ جان سه فاز 25 آمپر ویسنا"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
