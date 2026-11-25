import re
import unittest
from pathlib import Path

import fitz

from app.services.address_book_pdf_service import _meeting_row_font_size_pt, build_address_book_pdf
from app.services.field_list_service import (
    _field_list_print_css,
    _meeting_preview_row_print_html,
    _meeting_preview_row_style,
)
from app.services.meeting_v2_service import (
    MEETING_FONT_SIZE_OPTIONS,
    MEETING_ROW_FONT_SIZE_OPTIONS,
    _normalize_row_format_code,
)


_ROOT = Path(__file__).resolve().parents[1]
_LAYOUT = {
    "trim_width_in": 3.5,
    "trim_height_in": 5.5,
    "margin_left_in": 0.14,
    "margin_right_in": 0.14,
    "margin_top_in": 0.14,
    "margin_bottom_in": 0.14,
    "base_font_size_pt": 7,
    "line_height": 1.2,
    "font_family": "Arial",
    "book_title": "Blank Divider Spacing Book",
}


def _cell_row(text: str, font_size_pt: float = 7.0) -> dict:
    return {
        "kind": "cells",
        "font_size_pt": font_size_pt,
        "line_height": 1.2,
        "column_gap_px": 6,
        "grid_column_count": 28,
        "cells": [
            {
                "html": text,
                "align": "left",
                "col_start": 1,
                "col_span": 28,
                "is_bold": False,
                "is_italic": False,
                "is_underlined": False,
            }
        ],
    }


def _spacer_row(kind: str, font_size_pt: float) -> dict:
    return {
        "kind": kind,
        "font_size_pt": font_size_pt,
        "line_height": 1.2,
        "column_gap_px": 6,
        "grid_column_count": 28,
        "cells": [],
    }


def _meetingdata_pdf(rows: list[dict]) -> bytes:
    return build_address_book_pdf(
        fields=[{"name": "Field A", "meetings": [{"name": "Meeting 1", "contacts": []}]}],
        meeting_preview_sections=[{"field": "Field A", "meeting": "Meeting 1", "rows": rows}],
        settings={
            "address_map_provider": "google",
            "include_bible_study_union_info": 1,
            "meeting_page_mode": "one_meeting",
        },
        layout=_LAYOUT,
        print_order_mode="default",
        print_order_json="",
    )


def _label_top(pdf: bytes, label: str) -> float:
    document = fitz.open(stream=pdf, filetype="pdf")
    try:
        for page in document:
            text = page.get_text()
            if "Table of Contents" in text or "Index - Page" in text:
                continue
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                    if line_text == label:
                        return float(line["bbox"][1])
        raise AssertionError(f"missing {label!r}")
    finally:
        document.close()


def _gap_between(kind: str, font_size_pt: float) -> float:
    pdf = _meetingdata_pdf(
        [
            _cell_row("BeforeGap"),
            _spacer_row(kind, font_size_pt),
            _cell_row("AfterGap"),
        ]
    )
    return _label_top(pdf, "AfterGap") - _label_top(pdf, "BeforeGap")


def _css_block(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", css)
    if match is None:
        raise AssertionError(f"missing CSS rule for {selector}")
    return match.group(1)


class MeetingDataBlankDividerSpacingTests(unittest.TestCase):
    def test_spacer_font_size_options_start_at_1(self) -> None:
        self.assertEqual(MEETING_FONT_SIZE_OPTIONS[0], "5.0")
        self.assertEqual(MEETING_ROW_FONT_SIZE_OPTIONS[0], "1.0")
        self.assertIn("1.5", MEETING_ROW_FONT_SIZE_OPTIONS)
        self.assertIn("4.5", MEETING_ROW_FONT_SIZE_OPTIONS)
        self.assertNotIn("1.0", MEETING_FONT_SIZE_OPTIONS)
        self.assertEqual(MEETING_ROW_FONT_SIZE_OPTIONS[-1], MEETING_FONT_SIZE_OPTIONS[-1])

    def test_blank_and_divider_persist_font_sizes_below_5(self) -> None:
        self.assertEqual(_normalize_row_format_code("1.0", "blank"), "1.0")
        self.assertEqual(_normalize_row_format_code("4.5", "divider"), "4.5")
        self.assertEqual(_normalize_row_format_code("0.5", "blank"), "1.0")
        self.assertEqual(_normalize_row_format_code("1.0", "content"), "5.0")
        self.assertEqual(_normalize_row_format_code("4.5", "column_flow"), "5.0")
        self.assertEqual(_normalize_row_format_code("1.0", "content|underlined"), "5.0")
        self.assertEqual(_normalize_row_format_code("14.0", "blank"), "14.0")

    def test_pdf_uses_size_1_for_spacers_without_clamping_to_5(self) -> None:
        self.assertAlmostEqual(_meeting_row_font_size_pt({"kind": "blank", "font_size_pt": 1.0}, 7.0), 1.0)
        self.assertAlmostEqual(_meeting_row_font_size_pt({"kind": "divider", "font_size_pt": 1.0}, 7.0), 1.0)
        self.assertAlmostEqual(_meeting_row_font_size_pt({"kind": "cells", "font_size_pt": 1.0}, 7.0), 4.0)

    def test_pdf_blank_gap_grows_with_font_size(self) -> None:
        size_1 = _gap_between("blank", 1.0)
        size_5 = _gap_between("blank", 5.0)
        size_14 = _gap_between("blank", 14.0)
        self.assertGreater(size_5, size_1)
        self.assertGreater(size_14, size_5)
        self.assertAlmostEqual(size_5 - size_1, 4.0 * 1.2, delta=1.0)
        self.assertAlmostEqual(size_14 - size_5, 9.0 * 1.2, delta=1.0)

    def test_pdf_divider_gap_grows_with_font_size(self) -> None:
        size_1 = _gap_between("divider", 1.0)
        size_5 = _gap_between("divider", 5.0)
        size_14 = _gap_between("divider", 14.0)
        self.assertGreater(size_5, size_1)
        self.assertGreater(size_14, size_5)
        self.assertAlmostEqual(size_5 - size_1, 4.0 * 1.2, delta=1.0)
        self.assertAlmostEqual(size_14 - size_5, 9.0 * 1.2, delta=1.0)

    def test_editor_css_sizes_spacers_from_row_font(self) -> None:
        css = (_ROOT / "app/static/css/app.css").read_text()
        blank = _css_block(css, ".wysiwyg-blank-row-spacer")
        divider = _css_block(css, ".wysiwyg-divider-row-spacer")
        preview_blank = _css_block(css, ".field-list-meeting-preview-blank")
        self.assertIn("--row-base-font-px", blank)
        self.assertIn("--editor-line-height", blank)
        self.assertNotIn("0.12in", blank)
        self.assertIn("--row-base-font-px", divider)
        self.assertIn("--editor-line-height", divider)
        self.assertNotIn("18px", divider)
        self.assertIn("--meeting-row-font-size", preview_blank)
        self.assertIn("--meeting-row-line-height", preview_blank)
        self.assertNotIn("0.12in", preview_blank)

    def test_print_preview_css_sizes_spacers_from_row_em(self) -> None:
        html = (_ROOT / "app/templates/meetings/v2_print_preview.html").read_text()
        self.assertIn("height: calc(1em * {{ section.print_preview.line_height }});", html)
        self.assertNotIn("min-height: 0.12in;", html.split(".print-preview-spacer-blank")[1].split("}")[0])

    def test_field_list_print_html_uses_row_font_and_line_height(self) -> None:
        row = _spacer_row("blank", 9.0)
        style = _meeting_preview_row_style(row)
        self.assertIn("--meeting-row-font-size: 9.00pt", style)
        self.assertIn("--meeting-row-line-height: 1.20", style)
        html = _meeting_preview_row_print_html(row)
        self.assertIn("print-field-list-meeting-preview-blank", html)
        self.assertIn("--meeting-row-font-size: 9.00pt", html)
        divider_html = _meeting_preview_row_print_html(_spacer_row("divider", 11.0))
        self.assertIn("print-field-list-meeting-preview-divider", divider_html)
        self.assertIn("--meeting-row-font-size: 11.00pt", divider_html)
        size_1_html = _meeting_preview_row_print_html(_spacer_row("blank", 1.0))
        self.assertIn("--meeting-row-font-size: 1.00pt", size_1_html)

    def test_editor_font_size_dropdown_includes_size_1_for_spacers(self) -> None:
        html = (_ROOT / "app/templates/meetings/v2_section_editor.html").read_text()
        js = (_ROOT / "app/static/js/meeting_editor.js").read_text()
        self.assertIn("section.row_font_size_options", html)
        self.assertIn('row.row_kind_primary not in ["blank", "divider"]', html)
        self.assertIn("SPACER_ROW_FONT_SIZE_MIN_PT = 1", js)
        self.assertIn("CONTENT_ROW_FONT_SIZE_MIN_PT = 5", js)
        self.assertIn("function syncRowFontSizeOptions", js)

    def test_field_list_print_css_uses_font_size_variable(self) -> None:
        css = _field_list_print_css({"base_font_size_pt": 10, "line_height": 1.2})
        blank = _css_block(css, ".print-field-list-meeting-preview-blank")
        divider = _css_block(css, ".print-field-list-meeting-preview-divider")
        self.assertIn("--meeting-row-font-size", blank)
        self.assertIn("--meeting-row-line-height", blank)
        self.assertNotIn("0.12in", blank)
        self.assertIn("--meeting-row-font-size", divider)
        self.assertIn("--meeting-row-line-height", divider)


if __name__ == "__main__":
    unittest.main()
