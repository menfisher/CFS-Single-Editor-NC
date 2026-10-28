import unittest

import fitz

from app.services.address_book_pdf_service import (
    _html_styled_lines,
    _PdfLine,
    _pdf_line_style,
    build_address_book_pdf,
)


def _styled_runs(html: str) -> list[tuple[str, bool, bool, bool]]:
    lines = _html_styled_lines(html)
    return [
        (str(run.get("text") or ""), bool(run.get("bold")), bool(run.get("italic")), bool(run.get("underline")))
        for line in lines
        for run in line
    ]


def _span_is_italic(span: dict) -> bool:
    flags = int(span.get("flags") or 0)
    font = str(span.get("font") or "").lower()
    return bool(flags & 2) or "italic" in font or "oblique" in font


def _span_is_bold(span: dict) -> bool:
    flags = int(span.get("flags") or 0)
    font = str(span.get("font") or "").lower()
    return bool(flags & 16) or "bold" in font


def _meetingdata_pdf(*, html: str, is_italic: bool = False, is_bold: bool = False) -> bytes:
    return build_address_book_pdf(
        fields=[{"name": "Field A", "meetings": [{"name": "Meeting 1", "contacts": []}]}],
        meeting_preview_sections=[
            {
                "field": "Field A",
                "meeting": "Meeting 1",
                "rows": [
                    {
                        "kind": "cells",
                        "font_size_pt": 10.0,
                        "column_gap_px": 6,
                        "grid_column_count": 28,
                        "cells": [
                            {
                                "html": html,
                                "align": "left",
                                "col_start": 1,
                                "col_span": 28,
                                "is_bold": is_bold,
                                "is_italic": is_italic,
                                "is_underlined": False,
                            }
                        ],
                    }
                ],
            }
        ],
        settings={
            "address_map_provider": "google",
            "include_bible_study_union_info": 1,
            "meeting_page_mode": "one_meeting",
        },
        layout={
            "trim_width_in": 3.5,
            "trim_height_in": 5.5,
            "margin_left_in": 0.14,
            "margin_right_in": 0.14,
            "margin_top_in": 0.14,
            "margin_bottom_in": 0.14,
            "base_font_size_pt": 10,
            "line_height": 1.2,
            "font_family": "Arial",
            "book_title": "Italic MeetingData Book",
        },
        print_order_mode="default",
        print_order_json="",
    )


def _text_spans(pdf: bytes) -> list[dict]:
    document = fitz.open(stream=pdf, filetype="pdf")
    try:
        spans: list[dict] = []
        for page in document:
            if "Table of Contents" in page.get_text() or "Index - Page" in page.get_text():
                continue
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if str(span.get("text") or "").strip():
                            spans.append(span)
        return spans
    finally:
        document.close()


class MeetingDataHtmlItalicTests(unittest.TestCase):
    def test_em_and_i_become_italic_runs(self) -> None:
        self.assertEqual(
            _styled_runs("Hello <em>italic</em> and <i>also</i>"),
            [
                ("Hello ", False, False, False),
                ("italic", False, True, False),
                (" and ", False, False, False),
                ("also", False, True, False),
            ],
        )

    def test_strong_em_is_bold_and_italic(self) -> None:
        self.assertEqual(_styled_runs("<strong><em>both</em></strong>"), [("both", True, True, False)])

    def test_span_font_style_italic_is_kept(self) -> None:
        self.assertEqual(
            _styled_runs('Plain <span style="font-style: italic">tilted</span>'),
            [("Plain ", False, False, False), ("tilted", False, True, False)],
        )

    def test_underline_and_bold_still_parse(self) -> None:
        self.assertEqual(
            _styled_runs("<strong>Bold</strong> and <u>under</u>"),
            [("Bold", True, False, False), (" and ", False, False, False), ("under", False, False, True)],
        )


class MeetingDataPdfItalicTests(unittest.TestCase):
    def test_pdf_line_style_uses_italic_and_bolditalic(self) -> None:
        self.assertEqual(_pdf_line_style(_PdfLine("a", 0, 0, 10, italic=True)), "italic")
        self.assertEqual(_pdf_line_style(_PdfLine("a", 0, 0, 10, bold=True, italic=True)), "bolditalic")
        self.assertEqual(_pdf_line_style(_PdfLine("a", 0, 0, 10, bold=True)), "bold")

    def test_em_html_prints_with_italic_font(self) -> None:
        spans = _text_spans(_meetingdata_pdf(html="Please <em>italicize</em> this"))
        italic_span = next(span for span in spans if "italicize" in str(span.get("text") or ""))
        regular_span = next(span for span in spans if "Please" in str(span.get("text") or ""))
        self.assertTrue(_span_is_italic(italic_span), italic_span)
        self.assertFalse(_span_is_italic(regular_span), regular_span)

    def test_cell_italic_flag_prints_with_italic_font(self) -> None:
        spans = _text_spans(_meetingdata_pdf(html="Whole cell", is_italic=True))
        cell_span = next(span for span in spans if "Whole cell" in str(span.get("text") or ""))
        self.assertTrue(_span_is_italic(cell_span), cell_span)

    def test_bold_italic_html_prints_both_styles(self) -> None:
        spans = _text_spans(_meetingdata_pdf(html="<strong><em>BothStyles</em></strong>"))
        both = next(span for span in spans if "BothStyles" in str(span.get("text") or ""))
        self.assertTrue(_span_is_italic(both), both)
        self.assertTrue(_span_is_bold(both), both)


if __name__ == "__main__":
    unittest.main()
