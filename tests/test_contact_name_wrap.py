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
        self.assertGreaterEqual(len(lines), 3, lines)
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

    def test_children_that_fit_on_line_two_stay_off_line_one(self) -> None:
        contact = {
            "name": "GLAESER, BJOERN & Susannah",
            "children": ["Henry", "Eliana", "Jonah", "Matilda", "Sebastian"],
            "other_relationships": [],
        }
        # Parents plus every child is 68 columns; the child list alone is 40.
        lines = _wrap_contact_name_lines(contact, lambda text: float(len(text)), 45.0)
        self.assertEqual(lines[0], "GLAESER, BJOERN & Susannah;")
        self.assertNotIn("Henry", lines[0])
        self.assertNotIn("Sebastian", lines[0])
        self.assertEqual(lines[1], "Henry, Eliana, Jonah, Matilda, Sebastian")
        self.assertEqual(len(lines), 2, lines)
        joined = " ".join(lines)
        self.assertNotIn("...", joined)
        self.assertNotIn("\u2026", joined)

    def test_children_share_line_one_when_line_two_would_wrap(self) -> None:
        contact = {
            "name": "GLAESER, BJOERN & Susannah",
            "children": ["Henry", "Eliana", "Jonah", "Matilda", "Sebastian"],
            "other_relationships": [],
        }
        # The child list is 40 columns, so it cannot stay together on a 36-column line 2.
        lines = _wrap_contact_name_lines(contact, lambda text: float(len(text)), 36.0)
        self.assertEqual(
            lines,
            [
                "GLAESER, BJOERN & Susannah; Henry,",
                "Eliana, Jonah, Matilda, Sebastian",
            ],
        )
        self.assertIn("Henry", lines[0])
        self.assertNotIn("Eliana", lines[0])
        self.assertIn("Sebastian", lines[1])
        self.assertEqual(len(lines), 2, lines)
        joined = " ".join(lines)
        self.assertNotIn("...", joined)
        self.assertNotIn("\u2026", joined)

    def test_children_use_continuation_width_not_the_wider_first_line(self) -> None:
        contact = {
            "name": "GLAESER, BJOERN & Susannah",
            "children": ["Henry", "Eliana", "Jonah", "Matilda", "Sebastian"],
            "other_relationships": [],
        }
        # 40-column child list fits the 50-column parent line's remainder check,
        # but line 2 is only 30 columns, so the list must split.
        lines = _wrap_contact_name_lines(
            contact,
            lambda text: float(len(text)),
            30.0,
            first_line_max_width=50.0,
        )
        self.assertEqual(lines[0], "GLAESER, BJOERN & Susannah; Henry, Eliana, Jonah,")
        self.assertIn("Jonah", lines[0])
        self.assertNotIn("Matilda", lines[0])
        self.assertEqual(lines[1], "Matilda, Sebastian")
        self.assertEqual(len(lines), 2, lines)
        self.assertNotIn("...", " ".join(lines))

    def test_children_packing_uses_bold_surname_and_continuation_widths(self) -> None:
        from app.services.address_book_pdf_service import _contact_name_line_width, _text_width

        font_size = 7.0
        font_family = "Arial"
        head = "GLAESER, BJOERN & Susannah"
        children = ["Henry", "Eliana", "Jonah", "Matilda"]
        contact = {
            "name": head,
            "children": children,
            "other_relationships": [],
        }
        child_line = ", ".join(children)
        full = f"{head}; {child_line}"

        def measure(text: str) -> float:
            return _text_width(text, font_size, font_family)

        def measure_first(text: str) -> float:
            return _contact_name_line_width(text, font_size, font_family, bold_last_name=True)

        lines = _wrap_contact_name_lines(
            contact,
            measure,
            measure(child_line) + 12,
            first_line_measure_width=measure_first,
            first_line_max_width=measure_first(full),
        )
        self.assertEqual(lines, [full])
        self.assertIn("Eliana", lines[0])

        lines = _wrap_contact_name_lines(
            contact,
            measure,
            measure(child_line),
            first_line_measure_width=measure_first,
            first_line_max_width=measure_first(full) - 0.5,
        )
        self.assertEqual(lines, [f"{head};", child_line])
        self.assertNotIn("Henry", lines[0])

        one_child = f"{head}; {children[0]}"
        two_children = f"{head}; {children[0]}, {children[1]}"
        first_max = (measure_first(one_child) + measure_first(two_children)) / 2
        lines = _wrap_contact_name_lines(
            contact,
            measure,
            measure(child_line) - 0.5,
            first_line_measure_width=measure_first,
            first_line_max_width=first_max,
        )
        self.assertEqual(len(lines), 2, lines)
        self.assertIn(children[0], lines[0])
        self.assertNotIn(children[1], lines[0])
        self.assertIn(children[-1], lines[1])
        self.assertNotIn("...", " ".join(lines))
        self.assertNotIn("\u2026", " ".join(lines))

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

    def _name_rows(self, spans, markers):
        rows: dict[float, list] = {}
        for span in spans:
            if any(part in span["text"] for part in markers):
                rows.setdefault(round(span["bbox"][1], 1), []).append(span)
        lines = []
        for y in sorted(rows):
            parts = sorted(rows[y], key=lambda span: span["bbox"][0])
            lines.append("".join(str(span["text"]) for span in parts))
        return lines

    def test_pdf_children_that_fit_on_line_two_stay_off_line_one(self) -> None:
        children = ["Henry", "Eliana", "Jonah", "Matilda"]
        contact = {
            "name": "GLAESER, BJOERN & Susannah",
            "phones": [{"value": "7045551212", "code": "B"}],
            "addresses": [],
            "children": children,
            "other_relationships": [],
        }
        pdf = self._pdf_for_contact(contact)
        spans, text = self._name_spans(pdf)
        lines = self._name_rows(spans, ("GLAESER", *children))
        self.assertEqual(len(lines), 2, text)
        self.assertIn("GLAESER", lines[0])
        self.assertNotIn("Henry", lines[0])
        self.assertNotIn("Matilda", lines[0])
        for child in children:
            self.assertIn(child, lines[1], lines)
        self.assertNotIn("...", text)
        self.assertNotIn("\u2026", text)

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
        lines = self._name_rows(spans, ("GLAESER", *children))
        self.assertEqual(len(lines), 2, text)
        self.assertIn("Henry", lines[0])
        self.assertIn("Jonah", lines[0])
        self.assertNotIn("Matilda", lines[0])
        self.assertIn("Matilda", lines[1])
        self.assertIn("Genevieve", lines[1])
        self.assertIn("Theodore", lines[1])
        self.assertNotIn("...", text)
        self.assertNotIn("\u2026", text)


if __name__ == "__main__":
    unittest.main()
