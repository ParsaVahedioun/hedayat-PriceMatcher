"""Matching: inventory row in, price-list row out."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.matcher import Matcher, PriceIndex, prepare_stock  # noqa: E402
from core.pdf_reader import finalize  # noqa: E402
from models.product import PriceItem, StockItem, STATUS_NOT_FOUND  # noqa: E402


def price(code, value, section="", text=""):
    return finalize(PriceItem(code=code, price=value, section_fa=section,
                              text=text, page=1))


CATALOGUE = [
    price("SCAP-7", 141000, "پنل بک لایت آ پلاست", "وات۷ آفتابی مهتابی استاندارد"),
    price("SCAP-9", 177000, "پنل بک لایت آ پلاست", "وات۹ آفتابی مهتابی استاندارد"),
    price("SCAP-12", 297000, "پنل بک لایت آ پلاست", "وات۱۲ آفتابی مهتابی استاندارد"),
    price("VSDOBE-24", 280000, "پنل بک لایت اکو", "وات۲۴ آفتابی مهتابی استاندارد"),
    price("VSDOBE-24-P", 950000, "پنل سنسوردار روکار و توکار",
          "وات ۲۴ استاندارد آفتابی ۲۲۵ میلی متر"),
    price("VS6-1C(6-32)", 389000, "کلید های مینیاتوری تک پل",
          "کلید مینیاتوری تک پل - ۶ تا ۳۲ آ مپر ویسنا"),
    price("VS6-1C40", 391000, "کلید های مینیاتوری تک پل",
          "کلید مینیاتوری تک پل - ۴۰ آ مپر ویسنا"),
    price("VSR225.30-6", 2100000, "محافظ جان دو پل", "محافظ جان دو پل - ۲۵ آ مپر"),
    price("VSR425.30-6", 3200000, "محافظ جان چهار پل", "محافظ جان چهار پل - ۲۵ آ مپر"),
    price("SC886", 1190000, "چراغ سنسوردار", "چراغ سقفی سنسوردار پلاستیکی"),
]


class MatcherTestCase(unittest.TestCase):
    """Shared fixture: one catalogue, matched against one inventory name."""

    @classmethod
    def setUpClass(cls):
        cls.matcher = Matcher()
        cls.index = PriceIndex(CATALOGUE)

    def match(self, name):
        item = prepare_stock(StockItem(code="1", name=name, stock=1))
        return self.matcher.match_one(item, self.index)

    def assertPriced(self, name, code):
        result = self.match(name)
        self.assertIsNotNone(result.matched, f"{name} found no price row")
        self.assertEqual(result.matched.code, code)
        return result


class CodeMatchTests(MatcherTestCase):
    def test_an_identical_model_code_is_an_exact_match(self):
        result = self.assertPriced(
            "چراغ سقفی سنسور دار (پلاستیکی) IP20 شیله (SC886)", "SC886"
        )
        self.assertEqual(result.score, 100)

    def test_the_family_plus_the_wattage_picks_one_row_out_of_the_family(self):
        result = self.assertPriced(
            "پنل SMD توکار آ پلاست 9 وات گرد مهتابی شیله (SCAP)", "SCAP-9"
        )
        self.assertEqual(result.matched.price, 177000)

    def test_a_wattage_the_family_does_not_have_returns_nothing(self):
        result = self.match("پنل SMD توکار آ پلاست 33 وات گرد مهتابی شیله (SCAP)")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertIsNone(result.matched)


class VariantTests(MatcherTestCase):
    def test_the_plain_variant_is_not_priced_as_the_sensor_one(self):
        self.assertPriced(
            "پنل SMD توکار بک لایت 24 وات گرد مهتابی ویسنا (VSDOBE)", "VSDOBE-24"
        )

    def test_the_sensor_variant_is_not_priced_as_the_plain_one(self):
        self.assertPriced(
            "پنل SMD توکار بک لایت 24 وات سنسوردار گرد مهتابی ویسنا (VSDOBE)",
            "VSDOBE-24-P",
        )


class RatingTests(MatcherTestCase):
    def test_an_amperage_inside_a_range_row_matches_it(self):
        self.assertPriced(
            "کلید مینیاتوری تک فاز 16 آمپر (استاندارد) تیپ C ویسنا", "VS6-1C(6-32)"
        )

    def test_an_amperage_outside_the_range_takes_the_dedicated_row(self):
        self.assertPriced(
            "کلید مینیاتوری تک فاز 40 آمپر (استاندارد) تیپ C ویسنا", "VS6-1C40"
        )


class DomainVocabularyTests(MatcherTestCase):
    def test_a_single_phase_rccb_is_matched_to_the_two_pole_row(self):
        self.assertPriced("محافظ جان تک فاز 25 آمپر ویسنا", "VSR225.30-6")

    def test_a_three_phase_rccb_is_matched_to_the_four_pole_row(self):
        self.assertPriced("محافظ جان سه فاز 25 آمپر ویسنا", "VSR425.30-6")

    def test_a_breaker_is_never_priced_as_an_rccb(self):
        result = self.match("محافظ جان تک فاز 32 آمپر ویسنا")
        if result.matched is not None:
            self.assertNotIn("VS6", result.matched.code)


class BrandGateTests(MatcherTestCase):
    def test_another_vendors_product_is_left_without_a_price(self):
        result = self.match("لامپ LED حبابی 9 وات E27 مهتابی شوان")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertIsNone(result.matched)


class TargetBrandSpacingTests(unittest.TestCase):
    """A compound Persian brand name ("امیدنور") is spelled with or
    without the inner space depending on who typed it - the PDF's brand
    field and the inventory's product names very often disagree with each
    other on this, and neither spelling is "the" correct one."""

    def setUp(self):
        self.price_index = PriceIndex([
            price("1", 1800000, text="لامپ 7 وات ال ای دی اشکی شمعی"),
        ])

    def match(self, name, target_brand):
        matcher = Matcher({"target_brand": target_brand})
        item = prepare_stock(StockItem(code="1", name=name, stock=1), {})
        return matcher.match_one(item, self.price_index)

    def test_typed_brand_has_a_space_the_inventory_name_does_not(self):
        result = self.match("لامپ 7 وات ال ای دی اشکی شمعی امیدنور", "امید نور")
        self.assertIsNotNone(result.matched)

    def test_typed_brand_has_no_space_the_inventory_name_does(self):
        result = self.match("لامپ 7 وات ال ای دی اشکی شمعی امید نور", "امیدنور")
        self.assertIsNotNone(result.matched)

    def test_a_genuinely_different_brand_is_still_rejected(self):
        result = self.match("لامپ 7 وات ال ای دی اشکی شمعی شوان", "امیدنور")
        self.assertIsNone(result.matched)
        self.assertEqual(result.status, STATUS_NOT_FOUND)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
