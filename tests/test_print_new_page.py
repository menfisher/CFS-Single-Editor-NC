import tempfile
import unittest
from pathlib import Path

import fitz

from app.database import fetch_one, initialize_database, set_request_db_path
from app.services.address_book_pdf_service import build_address_book_pdf
from app.services.meeting_v2_service import (
    create_meeting_v2_section,
    get_meeting_v2_section_editor,
    save_meeting_v2_section,
)


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
}


def _page_texts(pdf: bytes) -> list[str]:
    document = fitz.open(stream=pdf, filetype="pdf")
    return [page.get_text() for page in document]


def _table_row(text: str, *, start: bool = False, end: bool = False, print_new_page: bool = False, group: str = "") -> dict:
    return {
        "kind": "cells",
        "is_table_start_row": start,
        "is_table_end_row": end,
        "print_new_page": print_new_page,
        "keep_together_group": group,
        "font_size_pt": 7.0,
        "column_gap_px": 6,
        "preview_printable_width_px": 220,
        "grid_column_count": 28,
        "cells": [{"html": text, "col_start": 1, "col_span": 28, "align": "auto"}],
    }


def _build_pdf(rows: list[dict], contact_count: int = 6) -> bytes:
    contacts = [{"name": f"Contact {index:02d}"} for index in range(1, contact_count + 1)]
    return build_address_book_pdf(
        fields=[{"name": "NC Eastern Field/Raleigh", "meetings": [{"name": "OXFORD", "contacts": contacts}]}],
        meeting_preview_sections=[{"field": "NC Eastern Field/Raleigh", "meeting": "OXFORD", "rows": rows}],
        settings={"meeting_page_mode": "one_meeting", "include_bible_study_union_info": 1},
        layout=_LAYOUT,
        print_order_mode="default",
        print_order_json="",
    )


class PrintNewPageTests(unittest.TestCase):
    def test_print_new_page_starts_a_new_page(self) -> None:
        rows = [
            _table_row("FieldListTable", start=True, end=True, print_new_page=True),
        ]
        pages = _page_texts(_build_pdf(rows))
        contact_pages = [index for index, text in enumerate(pages) if "Contact 01" in text]
        table_pages = [index for index, text in enumerate(pages) if "FieldListTable" in text]
        self.assertTrue(contact_pages, pages)
        self.assertTrue(table_pages, pages)
        self.assertGreater(table_pages[0], contact_pages[0])
        self.assertNotIn("FieldListTable", pages[contact_pages[0]])

    def test_print_new_page_keeps_grouped_tables_together(self) -> None:
        group = "block-0-group-with-table-below"
        rows = [
            _table_row("FirstGroupedTable", start=True, end=True, print_new_page=True, group=group),
            _table_row("SecondGroupedTable", start=True, end=True, group=group),
        ]
        pages = _page_texts(_build_pdf(rows))
        first_pages = [index for index, text in enumerate(pages) if "FirstGroupedTable" in text]
        second_pages = [index for index, text in enumerate(pages) if "SecondGroupedTable" in text]
        contact_pages = [index for index, text in enumerate(pages) if "Contact 01" in text]
        self.assertEqual(first_pages, second_pages)
        self.assertTrue(contact_pages)
        self.assertGreater(first_pages[0], contact_pages[0])
        self.assertIn("FirstGroupedTable", pages[first_pages[0]])
        self.assertIn("SecondGroupedTable", pages[first_pages[0]])
        self.assertNotIn("Contact 01", pages[first_pages[0]])

    def test_print_new_page_persists_on_a_table_start_row(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(tempdir.name) / "app.sqlite3")
        initialize_database()
        try:
            section_id = create_meeting_v2_section("NC Eastern Field/Raleigh", "Field list 1")
            section = get_meeting_v2_section_editor(section_id)
            row = section["rows"][0]
            save_meeting_v2_section(
                section_id,
                "",
                None,
                None,
                "CV",
                [
                    {
                        "id": row["id"],
                        "row_order": 1,
                        "row_kind": ["content", "table_start"],
                        "group_with_table_below": 1,
                        "no_meeting_association": 0,
                        "print_new_page": 1,
                        "format_code": "",
                        "label_text": "",
                        "notes": "",
                    }
                ],
                [],
            )
            saved = fetch_one(
                """
                SELECT print_new_page, group_with_table_below, row_kind
                FROM meeting_section_rows_v2
                WHERE id = ?
                """,
                (row["id"],),
            )
            reloaded = get_meeting_v2_section_editor(section_id)["rows"][0]
            self.assertEqual(int(saved["print_new_page"]), 1)
            self.assertEqual(int(saved["group_with_table_below"]), 1)
            self.assertIn("table_start", str(saved["row_kind"]))
            self.assertTrue(reloaded["print_new_page"])
            self.assertTrue(reloaded["group_with_table_below"])
        finally:
            set_request_db_path(None)
            tempdir.cleanup()


if __name__ == "__main__":
    unittest.main()
