import tempfile
import unittest
from pathlib import Path

import fitz

from app.database import initialize_database, set_request_db_path
from app.services.address_book_pdf_service import build_address_book_pdf
from app.services.field_list_service import _wrap_contact_name_lines, _wrap_relationship_text


class RelationshipWrapTests(unittest.TestCase):
    def test_wrapped_name_list_keeps_trailing_comma(self) -> None:
        lines = _wrap_relationship_text(
            "grandchildren: Jaylynn, Jathan, Aidan, Kaylynn, Isabella",
            lambda text: float(len(text)),
            40.0,
        )
        self.assertEqual(
            lines,
            ["grandchildren: Jaylynn, Jathan, Aidan,", "Kaylynn, Isabella"],
        )

    def test_contact_name_grandchildren_wrap_keeps_trailing_comma(self) -> None:
        contact = {
            "name": "HOCKERSMITH, Bruce",
            "children": [],
            "other_relationships": [
                {
                    "relation_type": "grandchildren",
                    "relation_value": "Jaylynn, Jathan, Aidan, Kaylynn, Isabella",
                }
            ],
        }
        lines = _wrap_contact_name_lines(contact, lambda text: float(len(text)), 40.0)
        self.assertGreaterEqual(len(lines), 3)
        self.assertEqual(lines[0], "HOCKERSMITH, Bruce")
        self.assertTrue(lines[1].rstrip().endswith(","), lines)
        self.assertFalse(lines[-1].rstrip().endswith(","), lines)

    def test_wrapped_child_uses_comma_not_semicolon(self) -> None:
        contact = {
            "name": "BERRY, Andrew & Christina",
            "children": ["Kynlee", "James", "Jack MOORE", "Lily", "Blakely BERRY"],
            "other_relationships": [],
        }
        lines = _wrap_contact_name_lines(contact, lambda text: float(len(text)), 32.0)
        self.assertEqual(lines[0], "BERRY, Andrew & Christina;")
        self.assertTrue(any("Lily" in line for line in lines), lines)
        self.assertTrue(any("Blakely BERRY" in line for line in lines), lines)
        joined = "\n".join(lines[1:])
        self.assertNotIn(";", joined)
        lily_line = next(line for line in lines if "Lily" in line)
        self.assertTrue(lily_line.rstrip().endswith(","), lines)

    def test_children_that_fit_without_ellipsis_stay_on_one_line(self) -> None:
        contact = {
            "name": "GLAESER, BJOERN & Susannah",
            "children": ["Henry", "Eliana"],
            "other_relationships": [],
        }
        full = "GLAESER, BJOERN & Susannah; Henry, Eliana"
        lines = _wrap_contact_name_lines(contact, lambda text: float(len(text)), float(len(full)))
        self.assertEqual(lines, [full])
        self.assertNotIn("...", "".join(lines))

    def test_children_use_remaining_first_line_then_wrap(self) -> None:
        contact = {
            "name": "GLAESER, BJOERN & Susannah",
            "children": ["Henry", "Eliana", "Jonah", "Matilda", "Sebastian"],
            "other_relationships": [],
        }
        lines = _wrap_contact_name_lines(contact, lambda text: float(len(text)), 45.0)
        self.assertTrue(lines[0].startswith("GLAESER, BJOERN & Susannah;"), lines)
        self.assertIn("Henry", lines[0])
        self.assertGreaterEqual(len(lines), 2, lines)
        joined = " ".join(lines)
        self.assertIn("Sebastian", joined)
        self.assertNotIn("...", joined)
        self.assertNotIn("\u2026", joined)

    def test_children_parsed_from_name_when_array_missing(self) -> None:
        contact = {
            "name": "GLAESER, BJOERN & Susannah; Henry, Eliana, Jonah",
            "children": [],
            "other_relationships": [],
        }
        lines = _wrap_contact_name_lines(contact, lambda text: float(len(text)), 40.0)
        joined = " ".join(lines)
        self.assertIn("Jonah", joined)
        self.assertNotIn("...", joined)
        self.assertGreaterEqual(len(lines), 2, lines)


class AddressBookChildrenPdfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self.tempdir.name) / "app.sqlite3")
        initialize_database()

    def tearDown(self) -> None:
        set_request_db_path(None)
        self.tempdir.cleanup()

    def _pdf_for_contact(self, contact: dict, *, width_in: float = 3.5, font_size: float = 7.0) -> bytes:
        return build_address_book_pdf(
            fields=[
                {
                    "name": "Field A",
                    "meetings": [
                        {
                            "name": "Meeting 1",
                            "contacts": [contact],
                        }
                    ],
                }
            ],
            meeting_preview_sections=[],
            settings={
                "address_map_provider": "google",
                "address_align": "right",
                "include_bible_study_union_info": 0,
                "meeting_page_mode": "one_meeting",
            },
            layout={
                "trim_width_in": width_in,
                "trim_height_in": 5.5,
                "margin_left_in": 0.14,
                "margin_right_in": 0.14,
                "margin_top_in": 0.14,
                "margin_bottom_in": 0.14,
                "base_font_size_pt": font_size,
                "line_height": 1.2,
                "font_family": "Arial",
                "book_title": "Children Wrap Book",
            },
            print_order_mode="alphabetical",
            print_order_json="",
        )

    def _name_spans(self, pdf: bytes):
        document = fitz.open(stream=pdf, filetype="pdf")
        try:
            page = next(item for item in document if "GLAESER" in item.get_text())
            return [
                span
                for block in page.get_text("dict").get("blocks", [])
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if str(span.get("text") or "")
            ], page.get_text()
        finally:
            document.close()

    def test_near_fitting_children_print_without_ellipsis(self) -> None:
        contact = {
            "name": "GLAESER, BJOERN & Susannah",
            "phones": [{"value": "7045551212", "code": "B"}],
            "addresses": [],
            "children": ["Henry", "Eliana"],
            "other_relationships": [],
        }
        pdf = self._pdf_for_contact(contact)
        spans, text = self._name_spans(pdf)
        self.assertIn("Eliana", text)
        self.assertNotIn("...", text)
        self.assertNotIn("\u2026", text)
        name_spans = [
            span for span in spans
            if any(part in span["text"] for part in ("GLAESER", "Susannah", "Henry", "Eliana"))
        ]
        ys = {round(span["bbox"][1], 1) for span in name_spans}
        self.assertEqual(len(ys), 1, text)

    def test_long_children_list_wraps_without_ellipsis(self) -> None:
        children = [
            "Henry",
            "Eliana",
            "Jonah",
            "Matilda",
            "Sebastian",
            "Penelope",
            "Theodore",
            "Genevieve",
        ]
        contact = {
            "name": "GLAESER, BJOERN & Susannah",
            "phones": [{"value": "7045551212", "code": "B"}],
            "addresses": [],
            "children": children,
            "other_relationships": [],
        }
        pdf = self._pdf_for_contact(contact)
        spans, text = self._name_spans(pdf)
        self.assertIn("Genevieve", text)
        self.assertIn("Theodore", text)
        self.assertNotIn("...", text)
        self.assertNotIn("\u2026", text)
        name_spans = [
            span for span in spans
            if any(part in span["text"] for part in ("GLAESER", *children))
        ]
        ys = {round(span["bbox"][1], 1) for span in name_spans}
        self.assertGreaterEqual(len(ys), 2, text)


if __name__ == "__main__":
    unittest.main()
