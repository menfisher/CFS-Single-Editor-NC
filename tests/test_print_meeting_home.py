import json
import tempfile
import unittest
from pathlib import Path

import fitz

from app.database import initialize_database, set_request_db_path
from app.routes.address_book import (
    _address_book_pdf_fields_from_context,
    _address_book_pdf_meeting_home_last_name,
)
from app.services.address_book_pdf_service import _meeting_heading, build_address_book_pdf
from app.services.field_list_service import get_address_book_settings, save_address_book_settings


_LAYOUT = {
    "book_title": "Test Book",
    "trim_width_in": 5.5,
    "trim_height_in": 8.5,
    "margin_left_in": 0.2,
    "margin_right_in": 0.2,
    "margin_top_in": 0.2,
    "margin_bottom_in": 0.2,
    "base_font_size_pt": 9,
    "title_font_size_pt": 12,
    "toc_font_size_pt": 9,
    "line_height": 1.2,
    "font_family": "Arial",
}


def _page_texts(pdf: bytes) -> list[str]:
    document = fitz.open(stream=pdf, filetype="pdf")
    return [page.get_text() for page in document]


def _joined_text(pdf: bytes) -> str:
    return "\n".join(_page_texts(pdf))


def _birmingham_fields(*, include_home: bool = True, include_elder: bool = True, group_parens: bool = False) -> list[dict]:
    contacts = []
    if include_home:
        contacts.append(
            {
                "name": "GRAHAM, Alice",
                "given_name": "Alice",
                "family_name": "GRAHAM",
                "mtg_home_elder_flag": "1",
            }
        )
    if include_elder:
        contacts.append(
            {
                "name": "ELDER, Bob",
                "given_name": "Bob",
                "family_name": "ELDER",
                "mtg_home_elder_flag": "2",
            }
        )
    contacts.append({"name": "Ada Lovelace"})
    meeting_name = "Birmingham (GRAHAM)" if group_parens else "Birmingham"
    return [
        {
            "name": "AL Central",
            "meetings": [
                {
                    "name": meeting_name,
                    "home_last_name": "GRAHAM" if include_home else "",
                    "contacts": contacts,
                }
            ],
        }
    ]


def _build(settings: dict, fields: list[dict] | None = None) -> bytes:
    defaults = {"meeting_page_mode": "one_meeting", "include_bible_study_union_info": 0}
    defaults.update(settings)
    return build_address_book_pdf(
        fields=_birmingham_fields() if fields is None else fields,
        meeting_preview_sections=[],
        settings=defaults,
        layout=_LAYOUT,
        print_order_mode="alphabetical",
        print_order_json="",
    )


class PrintMeetingHomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self._tempdir.name) / "app.sqlite3")
        initialize_database()

    def tearDown(self) -> None:
        set_request_db_path(None)
        self._tempdir.cleanup()

    def test_checkbox_is_under_one_meeting_per_page(self) -> None:
        html = Path("app/templates/address_book/pdf.html").read_text()
        js = Path("app/static/js/address_book_pdf.js").read_text()
        one_idx = html.find("1 mtg/page")
        complete_idx = html.find("Complete mtgs/page")
        home_idx = html.find("print mtg home after meeting")
        self.assertGreater(one_idx, 0)
        self.assertGreater(complete_idx, one_idx)
        self.assertGreater(home_idx, complete_idx)
        self.assertIn('name="print_meeting_home_after_meeting"', html)
        self.assertIn("addressBookPdfPrintMeetingHomeAfter", js)
        self.assertIn('name="print_meeting_home_after_meeting"', js)

    def test_heading_helper_off_prints_meeting_name_only(self) -> None:
        self.assertEqual(_meeting_heading("Birmingham", "GRAHAM"), "Birmingham")
        self.assertEqual(_meeting_heading("Birmingham (GRAHAM)", "GRAHAM"), "Birmingham")
        self.assertEqual(_meeting_heading("Birmingham", "GRAHAM", include_home=False), "Birmingham")

    def test_heading_helper_on_uses_home_in_parentheses(self) -> None:
        self.assertEqual(
            _meeting_heading("Birmingham", "GRAHAM", include_home=True),
            "Birmingham (Graham)",
        )
        self.assertEqual(
            _meeting_heading("Birmingham (GRAHAM)", "Graham", include_home=True),
            "Birmingham (Graham)",
        )

    def test_heading_helper_missing_home_has_no_empty_parentheses(self) -> None:
        self.assertEqual(_meeting_heading("Birmingham", "", include_home=True), "Birmingham")
        self.assertEqual(_meeting_heading("Birmingham (GRAHAM)", "", include_home=True), "Birmingham")
        self.assertNotIn("()", _meeting_heading("Birmingham", "  ", include_home=True))

    def test_pdf_off_prints_birmingham_without_home(self) -> None:
        text = _joined_text(_build({"print_meeting_home_after_meeting": 0}))
        self.assertIn("Birmingham", text)
        self.assertNotIn("Birmingham (Graham)", text)
        self.assertNotIn("Birmingham (GRAHAM)", text)
        self.assertNotIn("Birmingham (", text)

    def test_pdf_on_prints_birmingham_with_graham_home(self) -> None:
        text = _joined_text(_build({"print_meeting_home_after_meeting": 1}))
        self.assertIn("Birmingham (Graham)", text)
        self.assertNotIn("Birmingham (Elder)", text)
        self.assertNotIn("Birmingham (ELDER)", text)

    def test_pdf_missing_home_has_no_parentheses(self) -> None:
        fields = _birmingham_fields(include_home=False, group_parens=True)
        text = _joined_text(_build({"print_meeting_home_after_meeting": 1}, fields=fields))
        self.assertIn("Birmingham", text)
        self.assertNotIn("Birmingham (", text)
        self.assertNotIn("()", text)

    def test_pdf_does_not_use_elder_as_parenthetical(self) -> None:
        fields = _birmingham_fields(include_home=True, include_elder=True)
        home = _address_book_pdf_meeting_home_last_name(fields[0]["meetings"][0]["contacts"])
        self.assertEqual(home, "GRAHAM")
        text = _joined_text(_build({"print_meeting_home_after_meeting": 1}, fields=fields))
        self.assertIn("Birmingham (Graham)", text)
        self.assertNotIn("Birmingham (Elder)", text)

    def test_toc_and_separator_follow_the_same_heading(self) -> None:
        on_text = _joined_text(
            _build({"print_meeting_home_after_meeting": 1, "field_separator_pages": 1})
        )
        off_text = _joined_text(
            _build({"print_meeting_home_after_meeting": 0, "field_separator_pages": 1})
        )
        self.assertGreaterEqual(on_text.count("Birmingham (Graham)"), 3)
        self.assertIn("Birmingham", off_text)
        self.assertNotIn("Birmingham (Graham)", off_text)
        self.assertNotIn("Birmingham (", off_text)

    def test_preview_payload_uses_flag_one_not_elder(self) -> None:
        previewed = _address_book_pdf_fields_from_context(
            {"field_list_picker_json": json.dumps({"fields": _birmingham_fields()})}
        )
        meeting = previewed[0]["meetings"][0]
        self.assertEqual(meeting["home_last_name"], "GRAHAM")
        flags = [contact.get("mtg_home_elder_flag") for contact in meeting["contacts"]]
        self.assertIn("1", flags)
        self.assertIn("2", flags)

    def test_setting_persists_and_defaults_off(self) -> None:
        settings = get_address_book_settings()
        self.assertEqual(int(settings["print_meeting_home_after_meeting"]), 0)
        save_address_book_settings({"print_meeting_home_after_meeting": 1})
        saved = get_address_book_settings()
        self.assertEqual(int(saved["print_meeting_home_after_meeting"]), 1)
        save_address_book_settings({"print_meeting_home_after_meeting": 0})
        cleared = get_address_book_settings()
        self.assertEqual(int(cleared["print_meeting_home_after_meeting"]), 0)


if __name__ == "__main__":
    unittest.main()
