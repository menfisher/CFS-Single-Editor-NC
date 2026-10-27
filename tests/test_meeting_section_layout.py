import tempfile
import unittest
from pathlib import Path

from app.database import fetch_all, fetch_one, initialize_database, set_request_db_path
from app.services.meeting_v2_service import (
    _ensure_section_layout,
    add_meeting_v2_cell,
    create_meeting_v2_section,
    get_meeting_v2_section_editor,
    list_meeting_v2_sections,
    save_meeting_v2_section,
)


class MeetingSectionLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self._tempdir.name) / "app.sqlite3")
        initialize_database()

    def tearDown(self) -> None:
        set_request_db_path(None)
        self._tempdir.cleanup()

    def test_new_meeting_survives_opening_the_editor_list(self) -> None:
        section_id = create_meeting_v2_section("NC Eastern", "Oxford")
        list_meeting_v2_sections("", "NC Eastern", "")

        section = fetch_one("SELECT id FROM meeting_sections_v2 WHERE id = ?", (section_id,))
        layout = fetch_one(
            "SELECT id FROM meeting_section_layout_v2 WHERE section_id = ?",
            (section_id,),
        )
        self.assertIsNotNone(section)
        self.assertIsNotNone(layout)

    def test_add_meeting_v2_cell_can_add_one_two_or_three_cells(self) -> None:
        section_id = create_meeting_v2_section("NC Eastern", "Oxford")
        row_id = get_meeting_v2_section_editor(section_id)["rows"][0]["id"]

        def cell_count() -> int:
            return len(fetch_all("SELECT id FROM meeting_row_cells_v2 WHERE row_id = ?", (row_id,)))

        starting = cell_count()
        add_meeting_v2_cell(section_id, row_id)
        self.assertEqual(cell_count(), starting + 1)
        add_meeting_v2_cell(section_id, row_id, count=2)
        self.assertEqual(cell_count(), starting + 3)
        add_meeting_v2_cell(section_id, row_id, count=3)
        self.assertEqual(cell_count(), starting + 6)

    def test_meeting_line_height_defaults_and_persists(self) -> None:
        section_id = create_meeting_v2_section("NC Eastern", "Oxford")
        editor = get_meeting_v2_section_editor(section_id)
        self.assertAlmostEqual(editor["editor_canvas"]["line_height"], 1.2)
        row = editor["rows"][0]
        save_meeting_v2_section(
            section_id,
            "",
            editor["book_layout"]["book_layout_preset_id"],
            editor["editor_canvas"]["base_font_size_pt"],
            "CV",
            [
                {
                    "id": row["id"],
                    "row_order": 1,
                    "row_kind": "content",
                    "format_code": "",
                    "label_text": "",
                    "notes": "",
                }
            ],
            [],
            line_height=1.35,
        )
        reloaded = get_meeting_v2_section_editor(section_id)
        self.assertAlmostEqual(reloaded["editor_canvas"]["line_height"], 1.35)
        stored = fetch_one(
            "SELECT line_height FROM meeting_section_layout_v2 WHERE section_id = ?",
            (section_id,),
        )
        self.assertAlmostEqual(float(stored["line_height"]), 1.35)

    def test_missing_section_does_not_raise_when_preparing_layout(self) -> None:
        _ensure_section_layout(304719)
        layout = fetch_one(
            "SELECT id FROM meeting_section_layout_v2 WHERE section_id = ?",
            (304719,),
        )
        self.assertIsNone(layout)
