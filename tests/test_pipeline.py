"""End to end, on generated files - no real price list needed."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import pipeline  # noqa: E402
from core.exporter import export_excel  # noqa: E402


def _build_pdf(path):
    """A miniature price list with the same geometry as a real one."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    sheet = canvas.Canvas(path, pagesize=A4)
    sheet.setFont("Helvetica", 9)
    rows = [("SCAP-7", 7, "141,000"), ("SCAP-9", 9, "177,000"),
            ("SCAP-12", 12, "297,000")]
    sheet.drawString(400, 800, "A-plast Backlight Panel")
    for index, (code, watt, money) in enumerate(rows):
        y = 770 - index * 20
        sheet.drawString(450, y, code)          # right column: model code
        sheet.drawString(300, y, f"{watt} W")   # middle column: rating
        sheet.drawString(80, y, money)          # left column: price
    sheet.save()


def _build_excel(path):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["کد کالا", "نام کالا", "موجودی"])
    sheet.append([1001, "پنل SMD توکار آ پلاست 7 W گرد مهتابی شیله (SCAP)", 12])
    sheet.append([1002, "پنل SMD توکار آ پلاست 12 W گرد مهتابی شیله (SCAP)", 3])
    sheet.append([1003, "لامپ LED حبابی 9 وات E27 مهتابی شوان", 40])
    book.save(path)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._folder = tempfile.TemporaryDirectory()
        folder = cls._folder.name
        cls.pdf = os.path.join(folder, "price.pdf")
        cls.excel = os.path.join(folder, "stock.xlsx")
        _build_pdf(cls.pdf)
        _build_excel(cls.excel)
        cls.result = pipeline.run(cls.pdf, cls.excel)

    @classmethod
    def tearDownClass(cls):
        cls._folder.cleanup()

    def test_every_inventory_row_comes_back_exactly_once(self):
        self.assertEqual([row["code"] for row in self.result["rows"]],
                         ["1001", "1002", "1003"])

    def test_prices_are_attached_to_the_right_rows(self):
        rows = self.result["rows"]
        self.assertEqual(rows[0]["price"], 141000)
        self.assertEqual(rows[1]["price"], 297000)

    def test_a_product_of_another_vendor_gets_no_price(self):
        self.assertIsNone(self.result["rows"][2]["price"])

    def test_a_price_row_with_no_inventory_counterpart_is_never_shown(self):
        # SCAP-9 is in the price list but not in the inventory
        self.assertNotIn("SCAP-9", [row["pdf_code"] for row in self.result["rows"]])
        self.assertEqual(self.result["stats"]["priced"], 2)

    def test_the_excel_export_writes_a_usable_file(self):
        with tempfile.TemporaryDirectory() as folder:
            out = export_excel(self.result["rows"], os.path.join(folder, "out.xlsx"))
            self.assertGreater(os.path.getsize(out), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
