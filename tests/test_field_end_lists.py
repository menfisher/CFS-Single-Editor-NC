import tempfile
import unittest
from pathlib import Path

import fitz

from app.database import fetch_all, fetch_one, get_connection, initialize_database, set_request_db_path
from app.services.address_book_pdf_service import build_address_book_pdf, matching_contacts_meetings
from app.services.field_end_list_service import add_field_end_list, delete_field_end_list, rename_field_end_list, reorder_field_end_lists
from app.services.field_list_service import _field_list_picker_payload
from app.services.meeting_v2_service import list_meeting_v2_sections


class FieldEndListServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self._tempdir.name) / "app.sqlite3")
        initialize_database()

    def tearDown(self) -> None:
        set_request_db_path(None)
        self._tempdir.cleanup()

    def test_add_and_reorder_field_lists(self) -> None:
        add_field_end_list("NC Western Field", "Workers")
        add_field_end_list("NC Western Field", "Friends")
        add_field_end_list("NC Western Field", "Contacts")
        lists = reorder_field_end_lists(
            "NC Western Field",
            ["Friends", "Contacts", "Workers"],
        )
        self.assertEqual(
            [item["list_name"] for item in lists],
            ["Friends", "Contacts", "Workers"],
        )

    def test_add_field_list_opens_a_meetingdata_section(self) -> None:
        saved = add_field_end_list("NC Western Field", "Workers")
        section_id = int(saved.get("section_id") or 0)
        self.assertGreater(section_id, 0)
        self.assertEqual(saved.get("editor_url"), f"/meetings/v2/sections/{section_id}/editor#row-1")
        section = fetch_one(
            """
            SELECT field_name, meeting_name
            FROM meeting_sections_v2
            WHERE id = ?
            """,
            (section_id,),
        )
        self.assertIsNotNone(section)
        self.assertEqual(section["field_name"], "NC Western Field")
        self.assertEqual(section["meeting_name"], "Workers")
        listed = list_meeting_v2_sections("", "NC Western Field", "")
        self.assertIn("Workers", [item["meeting_name"] for item in listed])
        self.assertEqual(
            fetch_all(
                """
                SELECT value
                FROM contact_assignment_options
                WHERE kind = 'meeting' AND value = ?
                """,
                ("Workers",),
            ),
            [],
        )

    def test_orphaned_field_list_gets_a_meetingdata_section(self) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO field_end_lists (field_name, list_name, sort_order)
                VALUES ('NC Eastern Field/Raleigh', 'Field list 1', 1)
                """
            )
            conn.commit()
        saved = add_field_end_list("NC Eastern Field/Raleigh", "Field List 1")
        section_id = int(saved.get("section_id") or 0)
        self.assertGreater(section_id, 0)
        self.assertEqual(saved.get("list_name"), "Field list 1")
        section = fetch_one(
            """
            SELECT field_name, meeting_name
            FROM meeting_sections_v2
            WHERE id = ?
            """,
            (section_id,),
        )
        self.assertEqual(section["field_name"], "NC Eastern Field/Raleigh")
        self.assertEqual(section["meeting_name"], "Field list 1")
        listed = list_meeting_v2_sections("", "NC Eastern Field/Raleigh", "")
        self.assertIn("Field list 1", [item["meeting_name"] for item in listed])

    def test_rename_and_delete_field_list_updates_meetingdata(self) -> None:
        add_field_end_list("NC Eastern Field/Raleigh", "Temp Organize List")
        renamed = rename_field_end_list(
            "NC Eastern Field/Raleigh",
            "Temp Organize List",
            "Temp Organize Renamed",
        )
        self.assertEqual(renamed["list_name"], "Temp Organize Renamed")
        self.assertEqual(renamed["old_list_name"], "Temp Organize List")
        listed = list_meeting_v2_sections("", "NC Eastern Field/Raleigh", "")
        names = [item["meeting_name"] for item in listed]
        self.assertIn("Temp Organize Renamed", names)
        self.assertNotIn("Temp Organize List", names)
        section = fetch_one(
            """
            SELECT meeting_name
            FROM meeting_sections_v2
            WHERE id = ?
            """,
            (int(renamed["section_id"]),),
        )
        self.assertEqual(section["meeting_name"], "Temp Organize Renamed")
        removed = delete_field_end_list("NC Eastern Field/Raleigh", "Temp Organize Renamed")
        self.assertEqual(removed["value"], "Temp Organize Renamed")
        listed_after = list_meeting_v2_sections("", "NC Eastern Field/Raleigh", "")
        self.assertNotIn("Temp Organize Renamed", [item["meeting_name"] for item in listed_after])
        self.assertIsNone(
            fetch_one(
                """
                SELECT id
                FROM meeting_sections_v2
                WHERE field_name = ? AND meeting_name = ?
                """,
                ("NC Eastern Field/Raleigh", "Temp Organize Renamed"),
            )
        )

    def test_picker_prints_field_lists_after_meetings(self) -> None:
        add_field_end_list("NC Western Field", "Workers")
        add_field_end_list("NC Western Field", "Friends")
        reorder_field_end_lists("NC Western Field", ["Friends", "Workers"])
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO contacts (family_name, given_name, fields_text, meetings_text)
                VALUES
                  ('Avery', 'Ann', 'NC Western Field', 'ASHEVILLE'),
                  ('Baker', 'Ben', 'NC Western Field', 'GASTONIA'),
                  ('Cole', 'Cam', 'NC Western Field', 'Workers'),
                  ('Dale', 'Dee', 'NC Western Field', 'Friends')
                """
            )
            conn.commit()
        field = _field_list_picker_payload()["fields"][0]
        self.assertEqual(
            [meeting["name"] for meeting in field["meetings"]],
            ["ASHEVILLE", "GASTONIA", "Friends", "Workers"],
        )
        self.assertEqual(
            [bool(meeting.get("is_field_end_list")) for meeting in field["meetings"]],
            [False, False, True, True],
        )

    def test_picker_includes_field_lists_without_contacts(self) -> None:
        add_field_end_list("NC Western Field", "Workers")
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO contacts (family_name, given_name, fields_text, meetings_text)
                VALUES ('Avery', 'Ann', 'NC Western Field', 'ASHEVILLE')
                """
            )
            conn.commit()
        field = _field_list_picker_payload()["fields"][0]
        self.assertEqual(
            [meeting["name"] for meeting in field["meetings"]],
            ["ASHEVILLE", "Workers"],
        )
        workers = field["meetings"][1]
        self.assertTrue(workers.get("is_field_end_list"))
        self.assertEqual(workers.get("contacts"), [])


class FieldEndListPdfTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self._tempdir.name) / "app.sqlite3")
        initialize_database()

    def tearDown(self) -> None:
        set_request_db_path(None)
        self._tempdir.cleanup()

    def test_field_lists_print_after_the_fields_meetings(self) -> None:
        pdf = build_address_book_pdf(
            fields=[
                {
                    "name": "NC Western Field",
                    "meetings": [
                        {
                            "name": "ASHEVILLE",
                            "contacts": [{"name": "Ann Avery", "phones": [], "addresses": []}],
                        },
                        {
                            "name": "GASTONIA",
                            "contacts": [{"name": "Ben Baker", "phones": [], "addresses": []}],
                        },
                        {
                            "name": "Friends",
                            "is_field_end_list": True,
                            "field_end_list_order": 1,
                            "contacts": [{"name": "Dee Dale", "phones": [], "addresses": []}],
                        },
                        {
                            "name": "Workers",
                            "is_field_end_list": True,
                            "field_end_list_order": 2,
                            "contacts": [{"name": "Cam Cole", "phones": [], "addresses": []}],
                        },
                    ],
                }
            ],
            meeting_preview_sections=[],
            settings={"meeting_page_mode": "one_meeting", "include_bible_study_union_info": 0},
            layout={"trim_width_in": 8.5, "trim_height_in": 11, "base_font_size_pt": 10},
            print_order_mode="default",
            print_order_json="",
        )
        document = fitz.open(stream=pdf, filetype="pdf")
        headings = []
        for page in document:
            text = page.get_text().strip()
            first_line = text.splitlines()[0] if text else ""
            if first_line in {"ASHEVILLE", "GASTONIA", "Workers", "Friends"}:
                headings.append(first_line)
        self.assertEqual(headings, ["ASHEVILLE", "GASTONIA", "Friends", "Workers"])

    def test_field_end_contacts_list_is_not_folded_onto_a_meeting(self) -> None:
        meetings = [
            {"name": "ASHEVILLE", "contacts": [{"name": "Ann Avery"}]},
            {
                "name": "CONTACTS, Asheville Area",
                "is_field_end_list": True,
                "contacts": [{"name": "Cam Cole"}],
            },
        ]
        self.assertEqual(matching_contacts_meetings("ASHEVILLE", meetings), [])
        pdf = build_address_book_pdf(
            fields=[{"name": "NC Western Field", "meetings": meetings}],
            meeting_preview_sections=[],
            settings={"meeting_page_mode": "one_meeting", "include_bible_study_union_info": 0},
            layout={"trim_width_in": 8.5, "trim_height_in": 11, "base_font_size_pt": 10},
            print_order_mode="default",
            print_order_json="",
        )
        document = fitz.open(stream=pdf, filetype="pdf")
        pages = [page.get_text() for page in document]
        asheville_pages = [text for text in pages if text.startswith("ASHEVILLE")]
        self.assertEqual(len(asheville_pages), 1)
        self.assertNotIn("Cam Cole", asheville_pages[0])
        self.assertTrue(any(text.startswith("CONTACTS, Asheville Area") for text in pages))


if __name__ == "__main__":
    unittest.main()
