"""Multi-PDF batch pipeline: several price lists against one inventory.

`run_batch` delegates the actual PDF-reading/matching of each file to the
already-tested `run()`, so these tests mock `core.pipeline.run` and check
only the part that is new here: merging several per-file results into one
row set, in list order, with a "source" label per row.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import pipeline  # noqa: E402
from core.errors import AppError  # noqa: E402


def _row(code, name, price, status="HIGH"):
    return {
        "code": code, "name": name, "stock": 1, "price": price,
        "pdf_code": "", "pdf_name": "", "pdf_page": 0, "score": 90.0,
        "match_type": "text", "status": status if price is not None else "NOT_FOUND",
        "note": "", "alternatives": [],
    }


class BatchMergeTests(unittest.TestCase):
    def test_the_first_pdf_that_prices_a_row_wins(self):
        # both files could price row "1", but file A comes first in the list
        results = {
            "a.pdf": {"rows": [_row("1", "x", 100), _row("2", "y", None)],
                      "stats": {"pdf_rows": 1}},
            "b.pdf": {"rows": [_row("1", "x", 999), _row("2", "y", 200)],
                      "stats": {"pdf_rows": 1}},
        }

        def fake_run(pdf_path, excel_path, progress=None, config=None, brand=""):
            return results[pdf_path]

        with mock.patch("core.pipeline.run", side_effect=fake_run):
            out = pipeline.run_batch(
                [{"path": "a.pdf", "brand": "A", "name": "A"},
                 {"path": "b.pdf", "brand": "B", "name": "B"}],
                "stock.xlsx",
            )

        self.assertEqual(out["rows"][0]["price"], 100)      # A wins, not 999
        self.assertEqual(out["rows"][0]["source"], "A")
        self.assertEqual(out["rows"][1]["price"], 200)      # only B priced it
        self.assertEqual(out["rows"][1]["source"], "B")

    def test_a_row_no_pdf_priced_stays_unpriced_with_no_source(self):
        results = {"a.pdf": {"rows": [_row("1", "x", None)], "stats": {"pdf_rows": 0}}}

        def fake_run(pdf_path, excel_path, progress=None, config=None, brand=""):
            return results[pdf_path]

        with mock.patch("core.pipeline.run", side_effect=fake_run):
            out = pipeline.run_batch([{"path": "a.pdf", "brand": "A", "name": "A"}], "stock.xlsx")

        self.assertIsNone(out["rows"][0]["price"])
        self.assertEqual(out["rows"][0]["source"], "")

    def test_one_failing_pdf_does_not_stop_the_others(self):
        results = {"b.pdf": {"rows": [_row("1", "x", 55)], "stats": {"pdf_rows": 1}}}

        def fake_run(pdf_path, excel_path, progress=None, config=None, brand=""):
            if pdf_path == "a.pdf":
                raise AppError("این فایل خراب است")
            return results[pdf_path]

        with mock.patch("core.pipeline.run", side_effect=fake_run):
            out = pipeline.run_batch(
                [{"path": "a.pdf", "brand": "A", "name": "A"},
                 {"path": "b.pdf", "brand": "B", "name": "B"}],
                "stock.xlsx",
            )

        self.assertEqual(out["rows"][0]["price"], 55)
        files = {f["name"]: f for f in out["stats"]["files"]}
        self.assertFalse(files["A"]["ok"])
        self.assertEqual(files["A"]["error"], "این فایل خراب است")
        self.assertTrue(files["B"]["ok"])

    def test_no_pdf_entries_raises_a_clear_error(self):
        with self.assertRaises(AppError):
            pipeline.run_batch([], "stock.xlsx")

    def test_every_pdf_failing_raises_a_clear_error(self):
        def fake_run(pdf_path, excel_path, progress=None, config=None, brand=""):
            raise AppError("خراب")

        with mock.patch("core.pipeline.run", side_effect=fake_run):
            with self.assertRaises(AppError):
                pipeline.run_batch([{"path": "a.pdf", "brand": "A", "name": "A"}], "stock.xlsx")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
