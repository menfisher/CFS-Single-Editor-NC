import tempfile
import unittest
from pathlib import Path

import fitz

from app.database import initialize_database, set_request_db_path
from app.services.address_book_pdf_service import (
    PHONE_CODE_SLOT,
    _PdfImage,
    _PdfLine,
    _PdfWriter,
    _TocEntry,
    _build_toc_pages,
    _center_text_x,
    _contact_text_columns,
    _phone_code_for_line,
    _phone_display_text,
    _phone_letter_x,
    _phone_name_x,
    _phone_stack_to_name_width,
    _text_width,
    build_address_book_pdf,
)
from app.services.pdf_font_service import load_pdf_font, resolve_pdf_font_path


def _pdf_font_names(pdf: bytes) -> set[str]:
    document = fitz.open(stream=pdf, filetype="pdf")
    try:
        names = set()
        for page in document:
            for font in page.get_fonts(full=True):
                names.add(str(font[3] or ""))
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("text", "").strip():
                            names.add(str(span.get("font") or ""))
        return names
    finally:
        document.close()


class PdfEmbeddedFontTests(unittest.TestCase):
    def test_system_verdana_is_embedded_as_truetype(self) -> None:
        if not resolve_pdf_font_path("Verdana", "regular"):
            self.skipTest("Verdana is not installed on this computer")
        writer = _PdfWriter(200, 200, font_family="Verdana")
        page = writer.add_page()
        page.lines.append(_PdfLine("Verdana Sample", x=20, y=100, size=12))
        pdf = writer.bytes()
        names = " ".join(_pdf_font_names(pdf)).lower()
        self.assertIn("verdana", names)
        self.assertNotIn("helvetica", names)
        self.assertNotIn("arial", names)
        self.assertIn(b"/FontFile2", pdf)
        self.assertIn(b"/BaseFont/Verdana", pdf)
        self.assertNotIn(b"/CFSRegular", pdf)
        self.assertIn(b"/WinAnsiEncoding", pdf)
        self.assertIn(b"/ToUnicode", pdf)
        self.assertNotIn(b"/Verdana#20", pdf)
        document = fitz.open(stream=pdf, filetype="pdf")
        try:
            self.assertFalse(document.is_encrypted)
            self.assertFalse(document.needs_pass)
            self.assertTrue(document.permissions & fitz.PDF_PERM_MODIFY)
            self.assertTrue(document.permissions & fitz.PDF_PERM_ANNOTATE)
            self.assertTrue(document.permissions & fitz.PDF_PERM_ASSEMBLE)
            self.assertEqual(document.metadata.get("creator"), "ContactsFreeShare")
            self.assertEqual(document.metadata.get("producer"), "ContactsFreeShare")
        finally:
            document.close()

    def test_verdana_contact_name_wraps_like_the_html_preview(self) -> None:
        if not resolve_pdf_font_path("Verdana", "regular"):
            self.skipTest("Verdana is not installed on this computer")
        def tw(text: str, size: float) -> float:
            return _text_width(text, size, "Verdana")

        _phone_x, _code_x, _main_x, _cont_x, name_max = _contact_text_columns(
            0.14 * 72, 3.5 * 72, 0.14 * 72, 7, tw
        )
        full = "GRAHAM, Mark & Stephanie; Ruth, Harrison, Extra"
        head = "GRAHAM, Mark & Stephanie;"
        self.assertGreater(tw(full, 7), name_max)
        self.assertLessEqual(tw(head, 7), name_max)

    def test_phone_letter_follows_number_and_names_share_x(self) -> None:
        family = "Verdana" if resolve_pdf_font_path("Verdana", "regular") else "Arial"

        def tw(text: str, size: float) -> float:
            return _text_width(text, size, family)

        phone_x, _legacy_code_x, main_text_x, cont_x, _name_max = _contact_text_columns(
            0.14 * 72, 3.5 * 72, 0.14 * 72, 7, tw
        )
        ch = tw("0", 7)
        space = tw(" ", 7)
        slot = tw(PHONE_CODE_SLOT, 7)
        self.assertAlmostEqual(main_text_x - phone_x, _phone_stack_to_name_width(7, tw), places=5)
        self.assertAlmostEqual(cont_x - main_text_x, space, places=5)
        self.assertLess(main_text_x - phone_x, ch * 16)

        phone = _phone_display_text("704-965-6271")
        number_end = phone_x + tw(phone, 7)
        desired_letter = number_end + space
        name_xs = []
        for code in ("B", "c", "T", "Le", "B#"):
            letter_x = _phone_letter_x(phone, phone_x, main_text_x, 7, tw, code)
            self.assertAlmostEqual(letter_x, desired_letter, places=5)
            self.assertAlmostEqual(letter_x - number_end, space, places=5)
            self.assertLess(letter_x, phone_x + (ch * 13) - space)
            name_x = _phone_name_x(letter_x, code, 7, tw, main_text_x)
            self.assertAlmostEqual(name_x, main_text_x, places=5)
            name_xs.append(name_x)
        self.assertEqual(len(set(round(value, 5) for value in name_xs)), 1)

        name_x = _phone_name_x(desired_letter, "Sh", 7, tw, main_text_x)
        self.assertAlmostEqual(name_x, desired_letter + slot + space, places=5)

        other_letter_x = _phone_letter_x(phone, phone_x, main_text_x, 7, tw, "Sh")
        other_name_x = _phone_name_x(other_letter_x, "Sh", 7, tw, main_text_x)
        self.assertAlmostEqual(other_name_x, min(other_letter_x + slot + space, main_text_x), places=5)

        long_number = "1-800-555-12345"
        clamped = _phone_letter_x(long_number, phone_x, main_text_x, 7, tw, "wk")
        clamped_name = _phone_name_x(clamped, "wk", 7, tw, main_text_x)
        self.assertLessEqual(clamped + slot + space, main_text_x + 0.01)
        self.assertLess(clamped, phone_x + tw(long_number, 7) + space)
        self.assertLessEqual(clamped_name, main_text_x + 0.01)

    def test_pdf_phone_letter_gap_is_one_space_and_names_align(self) -> None:
        family = "Verdana" if resolve_pdf_font_path("Verdana", "regular") else "Arial"
        tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(tempdir.name) / "app.sqlite3")
        initialize_database()
        try:
            pdf = self._phone_gap_pdf(family)
        finally:
            set_request_db_path(None)
            tempdir.cleanup()
        self._assert_phone_gap_pdf(pdf, family)

    def _phone_gap_pdf(self, family: str) -> bytes:
        return build_address_book_pdf(
            fields=[
                {
                    "name": "Field A",
                    "meetings": [
                        {
                            "name": "Meeting 1",
                            "contacts": [
                                {
                                    "name": "THAIN, Sal",
                                    "phones": [{"value": "7049656271", "code": "Sh"}],
                                    "addresses": [],
                                    "children": [],
                                    "other_relationships": [],
                                },
                                {
                                    "name": "NELSON, Ned",
                                    "phones": [{"value": "3363820709", "code": "Sh"}],
                                    "addresses": [],
                                    "children": [],
                                    "other_relationships": [],
                                },
                            ],
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
                "trim_width_in": 3.5,
                "trim_height_in": 5.5,
                "margin_left_in": 0.14,
                "margin_right_in": 0.14,
                "margin_top_in": 0.14,
                "margin_bottom_in": 0.14,
                "base_font_size_pt": 7,
                "line_height": 1.2,
                "font_family": family,
                "book_title": "Phone Gap Book",
            },
            print_order_mode="alphabetical",
            print_order_json="",
        )

    def _assert_phone_gap_pdf(self, pdf: bytes, family: str) -> None:
        document = fitz.open(stream=pdf, filetype="pdf")
        try:
            page = next(item for item in document if "THAIN" in item.get_text() and "NELSON" in item.get_text())
            spans = [
                span
                for block in page.get_text("dict").get("blocks", [])
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if str(span.get("text") or "")
            ]
        finally:
            document.close()

        def _span(text: str):
            return next(span for span in spans if span["text"] == text)

        thain = _span("THAIN")
        nelson = _span("NELSON")
        self.assertAlmostEqual(thain["bbox"][0], nelson["bbox"][0], places=1)

        def tw(text: str, size: float) -> float:
            return _text_width(text, size, family)

        phone_x, _legacy_x, main_text_x, _cont_x, _name_max = _contact_text_columns(
            0.14 * 72, 3.5 * 72, 0.14 * 72, 7, tw
        )
        space = tw(" ", 7)
        self.assertAlmostEqual(thain["bbox"][0], main_text_x, places=1)

        phone_span = next(span for span in spans if "704-965-6271" in span["text"])
        old_tab_gap = _legacy_x - (phone_x + tw("704-965-6271", 7))
        if "Sh" in phone_span["text"]:
            code_end = phone_span["bbox"][0] + tw("704-965-6271 Sh", 7)
            gap = thain["bbox"][0] - code_end
            self.assertGreater(gap, space * 0.4)
            self.assertLess(gap, space * 1.8)
        else:
            letter_span = next(span for span in spans if span["text"] == "Sh")
            number_gap = letter_span["bbox"][0] - phone_span["bbox"][2]
            self.assertGreater(number_gap, space * 0.4)
            self.assertLess(number_gap, space * 1.8)
            self.assertAlmostEqual(number_gap, old_tab_gap, delta=0.05)
            name_gap = thain["bbox"][0] - letter_span["bbox"][2]
            self.assertGreater(name_gap, space * 0.4)
            self.assertLess(name_gap, space * 1.8)

    def test_one_and_two_letter_codes_share_name_column(self) -> None:
        family = "Verdana" if resolve_pdf_font_path("Verdana", "regular") else "Arial"
        tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(tempdir.name) / "app.sqlite3")
        initialize_database()
        try:
            pdf = build_address_book_pdf(
                fields=[
                    {
                        "name": "Field A",
                        "meetings": [
                            {
                                "name": "Meeting 1",
                                "contacts": [
                                    {
                                        "name": "NICHOLS, Maryann",
                                        "phones": [{"value": "3362018200", "code": "c"}],
                                        "addresses": [
                                            {
                                                "street_address": "100 Test Rd",
                                                "city": "Shelby",
                                                "region": "NC",
                                                "postal_code": "28150",
                                            }
                                        ],
                                        "children": ["Ada"],
                                        "other_relationships": [],
                                    },
                                    {
                                        "name": "SUMMEY, Leonard",
                                        "phones": [{"value": "3368348053", "code": "Le"}],
                                        "addresses": [
                                            {
                                                "street_address": "7500 Allen Rd",
                                                "city": "Shelby",
                                                "region": "NC",
                                                "postal_code": "28150",
                                            }
                                        ],
                                        "children": ["Hunter", "Sterling", "Madilynn", "Waylon"],
                                        "other_relationships": [],
                                    },
                                ],
                            }
                        ],
                    }
                ],
                meeting_preview_sections=[],
                settings={
                    "address_map_provider": "google",
                    "address_align": "left",
                    "include_bible_study_union_info": 0,
                    "meeting_page_mode": "one_meeting",
                },
                layout={
                    "trim_width_in": 3.5,
                    "trim_height_in": 5.5,
                    "margin_left_in": 0.14,
                    "margin_right_in": 0.14,
                    "margin_top_in": 0.14,
                    "margin_bottom_in": 0.14,
                    "base_font_size_pt": 7,
                    "line_height": 1.2,
                    "font_family": family,
                    "book_title": "Name Column Book",
                },
                print_order_mode="default",
                print_order_json="",
            )
        finally:
            set_request_db_path(None)
            tempdir.cleanup()

        document = fitz.open(stream=pdf, filetype="pdf")
        try:
            page = next(
                item for item in document if "NICHOLS" in item.get_text() and "SUMMEY" in item.get_text()
            )
            spans = [
                span
                for block in page.get_text("dict").get("blocks", [])
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if str(span.get("text") or "")
            ]
        finally:
            document.close()

        def _span(text: str):
            return next(span for span in spans if span["text"] == text)

        nichols = _span("NICHOLS")
        summey = _span("SUMMEY")
        self.assertAlmostEqual(nichols["bbox"][0], summey["bbox"][0], places=1)

        def tw(text: str, size: float) -> float:
            return _text_width(text, size, family)

        space = tw(" ", 7)
        child = next(span for span in spans if "Hunter" in (span.get("text") or "") and "SUMMEY" not in (span.get("text") or ""))
        address = next(span for span in spans if "7500" in (span.get("text") or ""))
        self.assertAlmostEqual(child["bbox"][0], summey["bbox"][0] + space, places=1)
        self.assertAlmostEqual(address["bbox"][0], summey["bbox"][0] + space, places=1)

        phone_span = next(span for span in spans if "336-834-8053" in span["text"])
        if "Le" in phone_span["text"]:
            letter_end = phone_span["bbox"][0] + tw("336-834-8053", 7) + space + tw("Le", 7)
            number_end = phone_span["bbox"][0] + tw("336-834-8053", 7)
            self.assertGreater(letter_end - number_end, space * 0.4)
            self.assertLess(letter_end - number_end - tw("Le", 7), space * 1.8)
        else:
            letter_span = next(span for span in spans if span["text"] == "Le")
            number_gap = letter_span["bbox"][0] - phone_span["bbox"][2]
            self.assertGreater(number_gap, space * 0.4)
            self.assertLess(number_gap, space * 1.8)

    def test_custom_phone_code_keeps_space_after_number(self) -> None:
        family = "Verdana" if resolve_pdf_font_path("Verdana", "regular") else "Arial"
        tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(tempdir.name) / "app.sqlite3")
        initialize_database()
        try:
            pdf = build_address_book_pdf(
                fields=[
                    {
                        "name": "Field A",
                        "meetings": [
                            {
                                "name": "Meeting 1",
                                "contacts": [
                                    {
                                        "name": "ARROW, Ann",
                                        "phones": [
                                            {
                                                "value": "7044778603",
                                                "code": "B",
                                                "type": "B",
                                                "custom_label": "B",
                                            },
                                            {
                                                "value": "7044771359",
                                                "code": "B",
                                                "type": "B#",
                                                "custom_label": "B#",
                                            },
                                        ],
                                        "addresses": [
                                            {
                                                "street_address": "444 E Davidson St",
                                                "city": "Shelby",
                                                "region": "NC",
                                                "postal_code": "28150",
                                            }
                                        ],
                                        "children": [],
                                        "other_relationships": [],
                                    },
                                    {
                                        "name": "SUMMEY, Leonard",
                                        "phones": [{"value": "3368348053", "code": "Le"}],
                                        "addresses": [],
                                        "children": [],
                                        "other_relationships": [],
                                    },
                                    {
                                        "name": "NICHOLS, Maryann",
                                        "phones": [
                                            {
                                                "value": "3362018200",
                                                "code": "B#",
                                                "type": "Blank",
                                                "phone_code": "B#",
                                            }
                                        ],
                                        "addresses": [],
                                        "children": [],
                                        "other_relationships": [],
                                    },
                                ],
                            }
                        ],
                    }
                ],
                meeting_preview_sections=[],
                settings={
                    "address_map_provider": "google",
                    "address_align": "left",
                    "include_bible_study_union_info": 0,
                    "meeting_page_mode": "one_meeting",
                },
                layout={
                    "trim_width_in": 3.5,
                    "trim_height_in": 5.5,
                    "margin_left_in": 0.14,
                    "margin_right_in": 0.14,
                    "margin_top_in": 0.14,
                    "margin_bottom_in": 0.14,
                    "base_font_size_pt": 7,
                    "line_height": 1.2,
                    "font_family": family,
                    "book_title": "Custom Code Gap Book",
                },
                print_order_mode="default",
                print_order_json="",
            )
        finally:
            set_request_db_path(None)
            tempdir.cleanup()

        document = fitz.open(stream=pdf, filetype="pdf")
        try:
            page = next(
                item
                for item in document
                if "ARROW" in item.get_text() and "SUMMEY" in item.get_text() and "B#" in item.get_text()
            )
            spans = [
                span
                for block in page.get_text("dict").get("blocks", [])
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if str(span.get("text") or "")
            ]
        finally:
            document.close()

        def _span(text: str):
            return next(span for span in spans if span["text"] == text)

        def tw(text: str, size: float) -> float:
            return _text_width(text, size, family)

        space = tw(" ", 7)
        arrow = _span("ARROW")
        summey = _span("SUMMEY")
        nichols = _span("NICHOLS")
        self.assertAlmostEqual(arrow["bbox"][0], summey["bbox"][0], places=1)
        self.assertAlmostEqual(summey["bbox"][0], nichols["bbox"][0], places=1)

        def number_to_letter_gap(last4: str, code: str) -> float:
            digit_span = next(
                span for span in spans if last4 in span["text"] and "-" in span["text"]
            )
            letter_span = next(
                span
                for span in spans
                if span["text"] == code
                and abs(span["bbox"][1] - digit_span["bbox"][1]) < 2
            )
            return letter_span["bbox"][0] - digit_span["bbox"][2]

        for last4, code in (("8603", "B"), ("1359", "B#"), ("8053", "Le"), ("8200", "B#")):
            gap = number_to_letter_gap(last4, code)
            self.assertGreater(gap, space * 0.85, msg=f"{code} after {last4}")
            self.assertLess(gap, space * 1.2, msg=f"{code} after {last4}")

    def test_phone_code_for_line_prints_full_hash_on_continuation(self) -> None:
        truncated = {
            "value": "7044771359",
            "code": "B",
            "type": "B#",
            "custom_label": "B#",
        }
        self.assertEqual(_phone_code_for_line(truncated, continuation=False), "B")
        self.assertEqual(_phone_code_for_line(truncated, continuation=True), "B#")
        household_b = {"value": "7044778603", "code": "B", "type": "B", "custom_label": "B"}
        self.assertEqual(_phone_code_for_line(household_b, continuation=False), "B")
        self.assertEqual(_phone_code_for_line(household_b, continuation=True), "B")

    def test_phone_code_for_line_skips_generic_custom_on_text_phones(self) -> None:
        text_phone = {
            "value": "# for texting",
            "code": "Cu",
            "type": "Custom",
            "custom_label": "Custom",
        }
        self.assertEqual(_phone_code_for_line(text_phone, continuation=False), "")
        self.assertEqual(_phone_code_for_line(text_phone, continuation=True), "")
        numeric_empty = {
            "value": "7044771359",
            "code": "Cu",
            "type": "Custom",
            "custom_label": "Custom",
        }
        self.assertEqual(_phone_code_for_line(numeric_empty, continuation=True), "")

    def _arrowood_print_pdf(self, family: str) -> bytes:
        return build_address_book_pdf(
            fields=[
                {
                    "name": "Field A",
                    "meetings": [
                        {
                            "name": "Meeting 1",
                            "contacts": [
                                {
                                    "name": "ARROWOOD, Ann",
                                    "phones": [
                                        {
                                            "value": "7044778603",
                                            "code": "B",
                                            "type": "B",
                                            "custom_label": "B",
                                        },
                                        {
                                            "value": "7044771359",
                                            "code": "B",
                                            "type": "B#",
                                            "custom_label": "B#",
                                        },
                                        {
                                            "value": "# for texting",
                                            "code": "Cu",
                                            "type": "Custom",
                                            "custom_label": "Custom",
                                        },
                                    ],
                                    "addresses": [
                                        {
                                            "street_address": "444 E Davidson St",
                                            "city": "Lawndale",
                                            "region": "NC",
                                            "postal_code": "28090",
                                        }
                                    ],
                                    "children": [],
                                    "other_relationships": [],
                                },
                                {
                                    "name": "SUMMEY, Leonard",
                                    "phones": [{"value": "3368348053", "code": "Le"}],
                                    "addresses": [],
                                    "children": [],
                                    "other_relationships": [],
                                },
                            ],
                        }
                    ],
                }
            ],
            meeting_preview_sections=[],
            settings={
                "address_map_provider": "google",
                "address_align": "left",
                "include_bible_study_union_info": 0,
                "meeting_page_mode": "one_meeting",
            },
            layout={
                "trim_width_in": 3.5,
                "trim_height_in": 5.5,
                "margin_left_in": 0.14,
                "margin_right_in": 0.14,
                "margin_top_in": 0.14,
                "margin_bottom_in": 0.14,
                "base_font_size_pt": 7,
                "line_height": 1.2,
                "font_family": family,
                "book_title": "Arrowood Print Book",
            },
            print_order_mode="default",
            print_order_json="",
        )

    def _pdf_spans(self, pdf: bytes):
        document = fitz.open(stream=pdf, filetype="pdf")
        try:
            page = next(
                item
                for item in document
                if "ARROWOOD" in item.get_text() and "SUMMEY" in item.get_text()
            )
            text = page.get_text()
            spans = [
                span
                for block in page.get_text("dict").get("blocks", [])
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if str(span.get("text") or "")
            ]
            return text, spans
        finally:
            document.close()

    def test_continuation_line_prints_full_custom_b_hash(self) -> None:
        family = "Verdana" if resolve_pdf_font_path("Verdana", "regular") else "Arial"
        tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(tempdir.name) / "app.sqlite3")
        initialize_database()
        try:
            pdf = self._arrowood_print_pdf(family)
        finally:
            set_request_db_path(None)
            tempdir.cleanup()

        text, spans = self._pdf_spans(pdf)

        def _span(value: str):
            return next(span for span in spans if span["text"] == value)

        def tw(value: str, size: float) -> float:
            return _text_width(value, size, family)

        space = tw(" ", 7)
        self.assertAlmostEqual(_span("ARROWOOD")["bbox"][0], _span("SUMMEY")["bbox"][0], places=1)
        self.assertIn("B#", text)
        digit_span = next(span for span in spans if "1359" in span["text"] and "-" in span["text"])
        letter_span = next(
            span
            for span in spans
            if span["text"] == "B#" and abs(span["bbox"][1] - digit_span["bbox"][1]) < 2
        )
        gap = letter_span["bbox"][0] - digit_span["bbox"][2]
        self.assertGreater(gap, space * 0.85)
        self.assertLess(gap, space * 1.2)
        self.assertEqual(letter_span["text"], "B#")
        address = next(span for span in spans if "444" in (span.get("text") or ""))
        self.assertGreater(address["bbox"][0], letter_span["bbox"][0] + tw("B", 7))

    def test_text_phone_with_empty_custom_label_does_not_print_custom(self) -> None:
        family = "Verdana" if resolve_pdf_font_path("Verdana", "regular") else "Arial"
        tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(tempdir.name) / "app.sqlite3")
        initialize_database()
        try:
            pdf = self._arrowood_print_pdf(family)
        finally:
            set_request_db_path(None)
            tempdir.cleanup()

        text, spans = self._pdf_spans(pdf)
        self.assertIn("# for texting", text)
        self.assertIn("Lawndale", text)
        self.assertNotIn("Custom", text)
        self.assertNotIn("Cu", [span["text"] for span in spans])
        self.assertTrue(any("# for texting" in span["text"] for span in spans))

    def test_toc_uses_chosen_title_and_entry_font_sizes(self) -> None:
        pages = _build_toc_pages(
            entries=[_TocEntry(field_name="Field A", meeting_heading="APEX", page=1)],
            book_title="NC Address Book",
            page_width=252,
            page_height=360,
            margin_left=10,
            margin_right=10,
            margin_top=10,
            margin_bottom=10,
            base_font_size=7,
            page_offset=0,
            compact=False,
            font_family="Arial",
            title_font_size=8,
            toc_font_size=7,
        )
        self.assertTrue(pages)
        sizes = {line.size for line in pages[0].lines}
        self.assertIn(8.0, sizes)
        self.assertIn(7.0, sizes)
        title = next(line for line in pages[0].lines if line.text.startswith("NC Address Book"))
        entry = next(line for line in pages[0].lines if line.text == "APEX")
        self.assertEqual(title.size, 8.0)
        self.assertEqual(entry.size, 7.0)
        self.assertAlmostEqual(
            title.x,
            _center_text_x(title.text, title.size, 252, 10, 10, "Arial", bold=True),
            places=4,
        )

    def test_address_book_pdf_keeps_verdana_instead_of_arial(self) -> None:
        if not resolve_pdf_font_path("Verdana", "regular"):
            self.skipTest("Verdana is not installed on this computer")
        pdf = build_address_book_pdf(
            fields=[
                {
                    "name": "Field A",
                    "meetings": [
                        {
                            "name": "Meeting 1",
                            "contacts": [
                                {
                                    "name": "DOE, John",
                                    "phones": [{"value": "5551234567", "code": "HM"}],
                                    "addresses": [],
                                    "children": [],
                                    "other_relationships": [],
                                }
                            ],
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
                "trim_width_in": 3.5,
                "trim_height_in": 5.5,
                "margin_left_in": 0.14,
                "margin_right_in": 0.14,
                "margin_top_in": 0.14,
                "margin_bottom_in": 0.14,
                "base_font_size_pt": 7,
                "line_height": 1.2,
                "font_family": "Verdana",
                "book_title": "Verdana Book",
            },
            print_order_mode="alphabetical",
            print_order_json="",
        )
        names = " ".join(_pdf_font_names(pdf)).lower()
        self.assertIn("verdana", names)
        self.assertNotIn("helvetica", names)
        self.assertNotIn("arial", names)
        self.assertIn(b"/FontFile2", pdf)

    def test_helvetica_keeps_the_built_in_pdf_font_when_no_ttf_is_installed(self) -> None:
        if resolve_pdf_font_path("Helvetica", "regular"):
            self.skipTest("A Helvetica TTF is installed, so it would be embedded")
        writer = _PdfWriter(200, 200, font_family="Helvetica")
        page = writer.add_page()
        page.lines.append(_PdfLine("Helvetica Sample", x=20, y=100, size=12))
        pdf = writer.bytes()
        names = " ".join(_pdf_font_names(pdf)).lower()
        self.assertIn("helv", names)
        self.assertNotIn("verdana", names)
        self.assertNotIn(b"/FontFile2", pdf)

    def test_flate_rgb_insert_image_does_not_crash_the_writer(self) -> None:
        import zlib

        rgb = bytes([20, 80, 160]) * (8 * 10)
        writer = _PdfWriter(80, 100, font_family="Verdana")
        page = writer.add_page()
        page.images.append(
            _PdfImage(
                zlib.compress(rgb, 9),
                8,
                10,
                0,
                0,
                80,
                100,
                filter_name="FlateDecode",
            )
        )
        page.lines.append(_PdfLine("Verdana Sample", x=8, y=20, size=10))
        pdf = writer.bytes()
        document = fitz.open(stream=pdf, filetype="pdf")
        try:
            self.assertTrue(document[0].get_images())
            names = " ".join(_pdf_font_names(pdf)).lower()
            self.assertIn("verdana", names)
        finally:
            document.close()

    def test_embedded_font_width_differs_from_helvetica_fallback(self) -> None:
        if load_pdf_font("Verdana", "regular") is None:
            self.skipTest("Verdana is not installed on this computer")
        verdana = _text_width("Washington", 12, "Verdana")
        helvetica = _text_width("Washington", 12, "Helvetica")
        self.assertNotAlmostEqual(verdana, helvetica, places=2)


if __name__ == "__main__":
    unittest.main()
