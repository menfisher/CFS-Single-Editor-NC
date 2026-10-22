import tempfile
import unittest
from pathlib import Path

from app.database import fetch_one, initialize_database, set_request_db_path
from app.services.meeting_v2_service import (
    _ensure_section_layout,
    create_meeting_v2_section,
    list_meeting_v2_sections,
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

    def test_missing_section_does_not_raise_when_preparing_layout(self) -> None:
        _ensure_section_layout(304719)
        layout = fetch_one(
            "SELECT id FROM meeting_section_layout_v2 WHERE section_id = ?",
            (304719,),
        )
        self.assertIsNone(layout)
