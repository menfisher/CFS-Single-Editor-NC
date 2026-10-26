import re
import tempfile
import unittest
from pathlib import Path

import fitz

from app.database import initialize_database, set_request_db_path
from app.services.address_book_pdf_service import build_address_book_pdf
from app.services.field_list_service import _parse_print_book_notes, print_book_note_display, print_book_note_runs


class PrintBookNoteSpacingTests(unittest.TestCase):
    def test_spaces_after_pb_and_pa_are_kept(self) -> None:
        before, after = _parse_print_book_notes("pb/  Tom is son\npa/  lives nearby")
        self.assertEqual(before, ["  Tom is son"])
        self.assertEqual(after, ["  lives nearby"])
        self.assertEqual(print_book_note_display(before[0]), "  Tom is son")
        self.assertEqual(print_book_note_display("Tom", default_gap=" "), " Tom")
        self.assertEqual(print_book_note_display(" (Tom is son)"), " (Tom is son)")
        self.assertEqual(print_book_note_display(after[0]), "  lives nearby")
        self.assertEqual(print_book_note_display(" (lives nearby)"), " (lives nearby)")

    def test_pb_and_pa_keep_bold_italic_and_underline(self) -> None:
        before, after = _parse_print_book_notes(
            "pb/ <strong>Tom</strong> is <em>son</em>\npa/ <u>lives</u> nearby"
        )
        before_runs = print_book_note_runs(before[0], default_gap=" ")
        after_runs = print_book_note_runs(after[0])
        self.assertEqual(print_book_note_display(before[0], default_gap=" "), " Tom is son")
        self.assertEqual(
            [(run["text"], run["bold"], run["italic"], run["underline"]) for run in before_runs],
            [(" ", False, False, False), ("Tom", True, False, False), (" is ", False, False, False), ("son", False, True, False)],
        )
        self.assertEqual(
            [(run["text"], run["underline"]) for run in after_runs if run["text"].strip()],
            [("lives", True), (" nearby", False)],
        )

    def test_pdf_name_line_uses_the_spaces_typed_after_pb(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self._tempdir.name) / "app.sqlite3")
        initialize_database()
        try:
            one_space = self._note_gap("SMITH, Ada", " Tom")
            two_spaces = self._note_gap("SMITH, Ada", "  Tom")
            typed_parentheses = self._page_text("SMITH, Ada", " (Tom)")
        finally:
            set_request_db_path(None)
            self._tempdir.cleanup()
        self.assertEqual(one_space, 1)
        self.assertEqual(two_spaces, 2)
        self.assertIn("Ada (Tom)", typed_parentheses)
        self.assertNotIn("((Tom))", typed_parentheses)

    def _page_text(self, name: str, note: str) -> str:
        pdf = build_address_book_pdf(
            fields=[
                {
                    "name": "NC Eastern",
                    "meetings": [
                        {
                            "name": "OXFORD",
                            "contacts": [
                                {
                                    "name": name.strip(),
                                    "phones": [],
                                    "addresses": [],
                                    "print_book_name": [note],
                                }
                            ],
                        }
                    ],
                }
            ],
            meeting_preview_sections=[],
            settings={"meeting_page_mode": "one_meeting", "include_bible_study_union_info": 0},
            layout={"trim_width_in": 8.5, "trim_height_in": 11, "base_font_size_pt": 10, "font_family": "Arial"},
            print_order_mode="default",
            print_order_json="",
        )
        document = fitz.open(stream=pdf, filetype="pdf")
        page = next(item for item in document if "OXFORD" in item.get_text() and "SMITH" in item.get_text())
        return page.get_text()

    def _note_gap(self, name: str, note: str) -> int:
        match = re.search(r"Ada( *)Tom", self._page_text(name, note))
        self.assertIsNotNone(match)
        return len(match.group(1))


class LeftAlignedContactBlockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self._tempdir.name) / "app.sqlite3")
        initialize_database()

    def tearDown(self) -> None:
        set_request_db_path(None)
        self._tempdir.cleanup()

    def test_left_aligned_address_lines_up_with_children_and_parentheses(self) -> None:
        pdf = build_address_book_pdf(
            fields=[
                {
                    "name": "NC Western Field/Charlotte",
                    "meetings": [
                        {
                            "name": "GASTONIA",
                            "contacts": [
                                {
                                    "name": "BROTHERTON, Katie & Matt",
                                    "children": ["Waylon", "Madilynn"],
                                    "phones": [],
                                    "addresses": [
                                        {
                                            "street_address": "220 St Paul Church Rd",
                                            "city": "Lawndale",
                                            "region": "NC",
                                            "postal_code": "28090-9231",
                                        }
                                    ],
                                },
                                {
                                    "name": "TODD, Deanna",
                                    "phones": [],
                                    "addresses": [
                                        {
                                            "street_address": "1500 Pasour Mountain Rd",
                                            "city": "Bessemer City",
                                            "region": "NC",
                                            "postal_code": "28016",
                                        }
                                    ],
                                    "print_after_address": ["(Melissa Pasour's sister)"],
                                },
                            ],
                        }
                    ],
                }
            ],
            meeting_preview_sections=[],
            settings={
                "meeting_page_mode": "one_meeting",
                "include_bible_study_union_info": 0,
                "address_align": "left",
            },
            layout={"trim_width_in": 3.5, "trim_height_in": 11, "base_font_size_pt": 10, "font_family": "Arial"},
            print_order_mode="default",
            print_order_json="",
        )
        document = fitz.open(stream=pdf, filetype="pdf")
        page = next(item for item in document if "BROTHERTON" in item.get_text() and "TODD" in item.get_text())
        left_edges: dict[str, float] = {}
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text") or ""
                    if "Waylon" in text and "BROTHERTON" not in text:
                        left_edges["children"] = span["bbox"][0]
                    elif text.startswith("220 "):
                        left_edges["brotherton_address"] = span["bbox"][0]
                    elif text.startswith("1500 "):
                        left_edges["todd_address"] = span["bbox"][0]
                    elif text.startswith("(Melissa"):
                        left_edges["parentheses"] = span["bbox"][0]
        self.assertEqual(
            set(left_edges),
            {"children", "brotherton_address", "todd_address", "parentheses"},
        )
        first = left_edges["children"]
        for label, left in left_edges.items():
            self.assertAlmostEqual(left, first, places=1, msg=label)
