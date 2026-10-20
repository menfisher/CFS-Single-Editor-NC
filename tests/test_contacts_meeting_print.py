import tempfile
import unittest
from pathlib import Path

import fitz

from app.database import initialize_database, set_request_db_path
from app.services.address_book_pdf_service import build_address_book_pdf, matching_contacts_meetings


def _meetings() -> list[dict]:
    return [
        {"name": "TRAPPE, MD", "contacts": [{"name": "Ada Trappe"}]},
        {"name": "CONTACTS, Trappe Area", "contacts": [{"name": "Bea Contact"}]},
        {"name": "VALE", "contacts": [{"name": "Cam Vale"}]},
        {"name": "VALDESE", "contacts": [{"name": "Dee Valdese"}]},
        {"name": "CONTACTS, Vale", "contacts": [{"name": "Eve Vale List"}]},
        {"name": "CONTACTS, Valdese", "contacts": [{"name": "Fay Valdese List"}]},
        {"name": "ROCK HILL (Brown)", "contacts": [{"name": "Gil Brown"}]},
        {"name": "CONTACTS, Rock Hill Area", "contacts": [{"name": "Hal Area"}]},
        {"name": "CONTACTS, Rock Hill, SC Area", "contacts": [{"name": "Ivy SC"}]},
        {"name": "SANFORD", "contacts": [{"name": "Jo Sanford"}]},
        {"name": "CONTACTS, Fayetteville & Sanford Areas", "contacts": [{"name": "Kim Shared"}]},
        {"name": "RALEIGH/WAKE FOREST", "contacts": [{"name": "Lee Raleigh"}]},
        {"name": "CONTACTS, Raleigh Area", "contacts": [{"name": "Mo Area"}]},
        {"name": "CONTACTS, Raleigh Field", "contacts": [{"name": "Ned Field"}]},
        {"name": "MILFORD, DE", "contacts": [{"name": "Ora Milford"}]},
        {"name": "CONTACTS, Delaware", "contacts": [{"name": "Pat Delaware"}]},
    ]


class ContactsMeetingMatchTests(unittest.TestCase):
    def test_trappe_matches_trappe_area_for_either_state(self) -> None:
        meetings = _meetings()
        self.assertEqual(
            [item["name"] for item in matching_contacts_meetings("TRAPPE, MD", meetings)],
            ["CONTACTS, Trappe Area"],
        )
        self.assertEqual(
            [item["name"] for item in matching_contacts_meetings("TRAPPE, ME", meetings)],
            ["CONTACTS, Trappe Area"],
        )

    def test_vale_does_not_match_valdese(self) -> None:
        meetings = _meetings()
        self.assertEqual(
            [item["name"] for item in matching_contacts_meetings("VALE", meetings)],
            ["CONTACTS, Vale"],
        )
        self.assertEqual(
            [item["name"] for item in matching_contacts_meetings("VALDESE", meetings)],
            ["CONTACTS, Valdese"],
        )

    def test_shared_area_name_matches_each_place(self) -> None:
        meetings = _meetings()
        self.assertEqual(
            [item["name"] for item in matching_contacts_meetings("SANFORD", meetings)],
            ["CONTACTS, Fayetteville & Sanford Areas"],
        )

    def test_raleigh_field_is_not_the_raleigh_meeting_list(self) -> None:
        meetings = _meetings()
        self.assertEqual(
            [item["name"] for item in matching_contacts_meetings("RALEIGH/WAKE FOREST", meetings)],
            ["CONTACTS, Raleigh Area"],
        )

    def test_state_name_does_not_match_a_city_meeting(self) -> None:
        meetings = _meetings()
        self.assertEqual(matching_contacts_meetings("MILFORD, DE", meetings), [])

    def test_contacts_list_is_not_paired_with_itself(self) -> None:
        meetings = _meetings()
        self.assertEqual(matching_contacts_meetings("CONTACTS, Trappe Area", meetings), [])


class ContactsMeetingPdfTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self._tempdir.name) / "app.sqlite3")
        initialize_database()

    def tearDown(self) -> None:
        set_request_db_path(None)
        self._tempdir.cleanup()

    def test_contacts_list_prints_on_the_meeting_page(self) -> None:
        pdf = build_address_book_pdf(
            fields=[
                {
                    "name": "Maryland and Delaware",
                    "meetings": [
                        {
                            "name": "TRAPPE, MD",
                            "contacts": [{"name": "Ada Trappe", "phones": [], "addresses": []}],
                        },
                        {
                            "name": "CONTACTS, Trappe Area",
                            "contacts": [{"name": "Bea Contact", "phones": [], "addresses": []}],
                        },
                        {
                            "name": "MILFORD, DE",
                            "contacts": [{"name": "Ora Milford", "phones": [], "addresses": []}],
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
        pages = [page.get_text() for page in document]
        meeting_pages = [text for text in pages if text.startswith("TRAPPE, MD")]
        self.assertEqual(len(meeting_pages), 1)
        self.assertIn("Ada Trappe", meeting_pages[0])
        self.assertIn("CONTACTS, Trappe Area", meeting_pages[0])
        self.assertIn("Bea Contact", meeting_pages[0])
        self.assertNotIn("Ora Milford", meeting_pages[0])
        self.assertFalse(any(text.startswith("CONTACTS, Trappe Area") for text in pages))
        self.assertTrue(any(text.startswith("MILFORD, DE") and "Bea Contact" not in text for text in pages))
        meeting_page = next(page for page in document if page.get_text().startswith("TRAPPE, MD"))
        positions = {}
        for block in meeting_page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if text in {"Ada Trappe", "CONTACTS, Trappe Area", "Bea Contact"} or text.startswith("Maryland and Delaware - Page"):
                    positions[text] = line["bbox"][1]
        self.assertLess(positions["Ada Trappe"], positions["CONTACTS, Trappe Area"])
        gap = positions["CONTACTS, Trappe Area"] - positions["Ada Trappe"]
        self.assertGreater(gap, 80)
        self.assertLess(positions["CONTACTS, Trappe Area"], positions["Bea Contact"])
        footer_key = next(key for key in positions if key.startswith("Maryland and Delaware - Page"))
        self.assertLess(positions["Bea Contact"], positions[footer_key])
        self.assertLess(positions[footer_key] - positions["Bea Contact"], 80)


if __name__ == "__main__":
    unittest.main()
