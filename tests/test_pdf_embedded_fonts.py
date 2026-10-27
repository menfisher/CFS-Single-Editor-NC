import tempfile
import unittest
from pathlib import Path

import fitz

from app.database import initialize_database, set_request_db_path
from app.services.address_book_pdf_service import (
    _PdfImage,
    _PdfLine,
    _PdfWriter,
    _TocEntry,
    _build_toc_pages,
    _center_text_x,
    _contact_text_columns,
    _phone_display_text,
    _phone_letter_x,
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
        self.assertNotIn(b"/Verdana#20", pdf)

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

        phone_x, _legacy_code_x, main_text_x, _cont_x, _name_max = _contact_text_columns(
            0.14 * 72, 3.5 * 72, 0.14 * 72, 7, tw
        )
        ch = tw("0", 7)
        space = tw(" ", 7)
        self.assertAlmostEqual((main_text_x - phone_x) / ch, 16.0, places=5)

        phone = _phone_display_text("704-965-6271")
        letter_x = _phone_letter_x(phone, phone_x, main_text_x, 7, tw, "M")
        self.assertAlmostEqual(letter_x, phone_x + tw(phone, 7) + space, places=5)
        self.assertLess(letter_x - (phone_x + tw(phone, 7)), space * 1.15)
        self.assertLess(letter_x, phone_x + (ch * 13) - space)

        two_letter_x = _phone_letter_x(phone, phone_x, main_text_x, 7, tw, "wk")
        self.assertLessEqual(two_letter_x + tw("wk", 7) + space, main_text_x + 0.01)

        other_phone_x, _other_legacy, other_main_x, _other_cont, _other_max = _contact_text_columns(
            0.14 * 72, 3.5 * 72, 0.14 * 72, 7, tw
        )
        self.assertAlmostEqual(main_text_x, other_main_x, places=5)
        self.assertAlmostEqual(phone_x, other_phone_x, places=5)

        long_number = "1-800-555-12345"
        clamped = _phone_letter_x(long_number, phone_x, main_text_x, 7, tw, "wk")
        self.assertLessEqual(clamped + tw("wk", 7) + space, main_text_x + 0.01)
        self.assertLess(clamped, phone_x + tw(long_number, 7) + space)

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
                                    "name": "ADAMS, Ann",
                                    "phones": [{"value": "7049656271", "code": "M"}],
                                    "addresses": [],
                                    "children": [],
                                    "other_relationships": [],
                                },
                                {
                                    "name": "BAKER, Ben",
                                    "phones": [{"value": "3363820709", "code": "S"}],
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
            page = next(item for item in document if "ADAMS" in item.get_text() and "BAKER" in item.get_text())
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

        adams = _span("ADAMS")
        baker = _span("BAKER")
        self.assertAlmostEqual(adams["bbox"][0], baker["bbox"][0], places=1)

        def tw(text: str, size: float) -> float:
            return _text_width(text, size, family)

        _phone_x, _legacy_x, main_text_x, _cont_x, _name_max = _contact_text_columns(
            0.14 * 72, 3.5 * 72, 0.14 * 72, 7, tw
        )
        self.assertAlmostEqual(adams["bbox"][0], main_text_x, places=1)

        phone_span = next(span for span in spans if "704-965-6271" in span["text"])
        space = tw(" ", 7)
        old_tab_gap = _legacy_x - (_phone_x + tw("704-965-6271", 7))
        if phone_span["text"] == "704-965-6271 M":
            drawn_width = phone_span["bbox"][2] - phone_span["bbox"][0]
            self.assertAlmostEqual(drawn_width, tw("704-965-6271 M", 7), places=1)
            self.assertLess(drawn_width + 1.0, (_legacy_x - _phone_x) + tw("M", 7))
        else:
            letter_span = next(span for span in spans if span["text"] == "M")
            gap = letter_span["bbox"][0] - phone_span["bbox"][2]
            self.assertGreater(gap, space * 0.4)
            self.assertLess(gap, space * 1.8)
            self.assertLess(gap, old_tab_gap)

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
