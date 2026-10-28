import tempfile
import unittest
from pathlib import Path

from app.database import initialize_database, set_request_db_path
import fitz

from app.services.address_book_pdf_service import _is_home_phone_type, build_address_book_pdf
from app.services.contact_service import create_contact, get_contact_detail
from app.services.field_list_service import (
    _field_list_contact_payload,
    _format_contact_phones,
    _format_raw_phone_type_code,
    _is_blank_phone_type,
    _is_generic_custom_phone_type,
    _known_phone_code,
    _order_household_phones,
)


class BlankPhoneLabelTests(unittest.TestCase):
    def test_blank_is_a_known_type_with_no_letter(self) -> None:
        self.assertTrue(_is_blank_phone_type("Blank"))
        self.assertTrue(_is_blank_phone_type(""))
        self.assertTrue(_is_blank_phone_type("no label"))
        self.assertEqual(_known_phone_code("Blank"), "")
        self.assertEqual(_known_phone_code(""), "")

    def test_blank_phone_prints_in_the_phone_column_without_a_code(self) -> None:
        phones = _format_contact_phones(
            {
                "given_name": "Ada",
                "name": "SMITH, Ada",
                "relationships": [],
                "phones": [
                    {"phone_type": "Blank", "phone_value": "see notes in"},
                    {"phone_type": "Mobile", "phone_value": "704-965-6271"},
                ],
            }
        )
        self.assertEqual(phones[0]["value"], "see notes in")
        self.assertEqual(phones[0]["code"], "")
        self.assertEqual(phones[0]["custom_label"], "")
        self.assertEqual(phones[1]["code"], "c")

    def test_blank_stays_letterless_in_a_household(self) -> None:
        phones = _format_contact_phones(
            {
                "given_name": "Ada",
                "name": "SMITH, Ada & Ben",
                "relationships": [{"relation_type": "spouse", "relation_value": "Ben"}],
                "phones": [
                    {"phone_type": "Blank", "phone_value": "see notes in"},
                    {"phone_type": "Mobile", "phone_value": "704-965-6271"},
                ],
            }
        )
        self.assertEqual(phones[0]["value"], "see notes in")
        self.assertEqual(phones[0]["code"], "")
        self.assertEqual(phones[0]["custom_label"], "")

    def test_blank_extra_box_prints_in_the_letter_column(self) -> None:
        phones = _format_contact_phones(
            {
                "given_name": "Ada",
                "name": "SMITH, Ada",
                "relationships": [],
                "phones": [
                    {
                        "phone_type": "Blank",
                        "phone_value": "704-965-6271",
                        "phone_code": "S",
                    }
                ],
            }
        )
        self.assertEqual(phones[0]["value"], "704-965-6271")
        self.assertEqual(phones[0]["code"], "S")
        self.assertEqual(phones[0]["phone_code"], "S")

    def test_blank_phone_column_keeps_text_that_fits_12ch(self) -> None:
        phones = _format_contact_phones(
            {
                "given_name": "Ada",
                "phones": [
                    {"phone_type": "Blank", "phone_value": "# for texting"},
                    {"phone_type": "Blank", "phone_value": "000000000000000"},
                    {"phone_type": "Mobile", "phone_value": "704-965-6271 x999"},
                ],
            }
        )
        self.assertEqual(phones[0]["value"], "# for texting")
        self.assertEqual(phones[1]["value"], "000000000000")
        self.assertEqual(phones[2]["value"], "704-965-6271 x999")


class CustomPhoneCodeTests(unittest.TestCase):
    def test_raw_codes_keep_hash_and_skip_generic_custom(self) -> None:
        self.assertTrue(_is_generic_custom_phone_type("Custom"))
        self.assertFalse(_is_generic_custom_phone_type("B"))
        self.assertFalse(_is_generic_custom_phone_type("B#"))
        self.assertEqual(_format_raw_phone_type_code("B"), "B")
        self.assertEqual(_format_raw_phone_type_code("B#"), "B#")
        self.assertEqual(_format_raw_phone_type_code("Custom"), "")
        self.assertEqual(_format_raw_phone_type_code("Grandma"), "Gr")

    def test_custom_b_hash_keeps_punctuation_in_code(self) -> None:
        phones = _format_contact_phones(
            {
                "given_name": "Ann",
                "name": "ARROWOOD, Ann",
                "phones": [
                    {"phone_type": "B", "phone_value": "704-477-8603"},
                    {"phone_type": "B#", "phone_value": "704-477-1359"},
                    {"phone_type": "Custom", "phone_value": "# for texting"},
                ],
            }
        )
        self.assertEqual(phones[0]["code"], "B")
        self.assertEqual(phones[1]["code"], "B#")
        self.assertEqual(phones[1]["custom_label"], "B#")
        self.assertEqual(phones[2]["value"], "# for texting")
        self.assertEqual(phones[2]["code"], "")
        self.assertEqual(phones[2]["custom_label"], "")

    def test_empty_custom_label_is_not_a_letter_on_numeric_phones(self) -> None:
        phones = _format_contact_phones(
            {
                "given_name": "Ann",
                "phones": [
                    {"phone_type": "Custom", "phone_value": "704-477-1359"},
                ],
            }
        )
        self.assertEqual(phones[0]["code"], "")
        self.assertEqual(phones[0]["custom_label"], "")


class PhonePrintOrderTests(unittest.TestCase):
    def test_format_keeps_custom_then_blank_edit_order(self) -> None:
        phones = _format_contact_phones(
            {
                "given_name": "Ada",
                "phones": [
                    {"phone_type": "B", "phone_value": "704-477-8603"},
                    {"phone_type": "B#", "phone_value": "704-477-1359"},
                    {"phone_type": "Blank", "phone_value": "# for texting"},
                ],
            }
        )
        self.assertEqual(
            [item["value"] for item in phones],
            ["704-477-8603", "704-477-1359", "# for texting"],
        )

    def test_format_keeps_edit_page_order(self) -> None:
        phones = _format_contact_phones(
            {
                "given_name": "Ada",
                "phones": [
                    {"phone_type": "Work", "phone_value": "999-000-1111"},
                    {"phone_type": "Blank", "phone_value": "call after 6"},
                    {"phone_type": "Mobile", "phone_value": "111-222-3333"},
                ],
            }
        )
        self.assertEqual(
            [item["value"] for item in phones],
            ["999-000-1111", "call after 6", "111-222-3333"],
        )

    def test_household_sort_keeps_each_persons_edit_order(self) -> None:
        phones = [
            {"value": "999-000-0000", "code": "c", "owner_given_name": "Ben"},
            {"value": "111-000-0000", "code": "", "owner_given_name": "Ada"},
            {"value": "888-000-0000", "code": "wk", "owner_given_name": "Ada"},
            {"value": "222-000-0000", "code": "c", "owner_given_name": "Ada"},
        ]
        ordered = _order_household_phones(phones, ["Ada", "Ben"])
        self.assertEqual(
            [item["value"] for item in ordered],
            ["111-000-0000", "888-000-0000", "222-000-0000", "999-000-0000"],
        )

    def test_payload_keeps_edit_order_and_blank_has_no_letter(self) -> None:
        payload = _field_list_contact_payload(
            {
                "id": 1,
                "family_name": "Smith",
                "given_name": "Ada",
                "relationships": [],
                "addresses": [],
                "fields_list": ["NC"],
                "meetings_list": ["OXFORD"],
                "phones": [
                    {"phone_type": "Work", "phone_value": "999-000-1111"},
                    {"phone_type": "Blank", "phone_value": "see notes in"},
                    {"phone_type": "Mobile", "phone_value": "111-222-3333"},
                ],
            }
        )
        self.assertEqual(
            [(item["value"], item["code"]) for item in payload["phones"]],
            [
                ("999-000-1111", "wk"),
                ("see notes in", ""),
                ("111-222-3333", "c"),
            ],
        )

    def test_payload_keeps_custom_then_blank_edit_order(self) -> None:
        payload = _field_list_contact_payload(
            {
                "id": 1,
                "family_name": "Smith",
                "given_name": "Ada",
                "relationships": [],
                "addresses": [],
                "fields_list": ["NC"],
                "meetings_list": ["OXFORD"],
                "phones": [
                    {"phone_type": "B", "phone_value": "704-477-8603"},
                    {"phone_type": "B#", "phone_value": "704-477-1359"},
                    {"phone_type": "Blank", "phone_value": "# for texting"},
                ],
            }
        )
        self.assertEqual(
            [item["value"] for item in payload["phones"]],
            ["704-477-8603", "704-477-1359", "# for texting"],
        )
        self.assertEqual(payload["phones"][2]["value"], "# for texting")
        self.assertEqual(len(payload["phones"][2]["value"]), 13)

    def test_payload_prints_blank_extra_box_in_letter_column(self) -> None:
        payload = _field_list_contact_payload(
            {
                "id": 1,
                "family_name": "Smith",
                "given_name": "Ada",
                "relationships": [],
                "addresses": [],
                "fields_list": ["NC"],
                "meetings_list": ["OXFORD"],
                "phones": [
                    {
                        "phone_type": "Blank",
                        "phone_value": "704-965-6271",
                        "phone_code": "wk",
                    }
                ],
            }
        )
        self.assertEqual(payload["phones"][0]["value"], "704-965-6271")
        self.assertEqual(payload["phones"][0]["code"], "wk")


class BlankPhoneRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self._tempdir.name) / "app.sqlite3")
        initialize_database()

    def tearDown(self) -> None:
        set_request_db_path(None)
        self._tempdir.cleanup()

    def test_blank_label_reloads_and_keeps_edit_order(self) -> None:
        contact_id = create_contact(
            {
                "family_name": "Smith",
                "given_name": "Ada",
                "phone_type": ["B", "B#", "Blank"],
                "phone_value": ["704-477-8603", "704-477-1359", "# for texting"],
                "phone_code": ["", "", ""],
            }
        )
        contact = get_contact_detail(contact_id)
        self.assertIsNotNone(contact)
        phones = contact["phones"]
        self.assertEqual(
            [(item["phone_type"], item["phone_value"], item.get("phone_code") or "") for item in phones],
            [
                ("B", "704-477-8603", ""),
                ("B#", "704-477-1359", ""),
                ("Blank", "# for texting", ""),
            ],
        )
        formatted = _format_contact_phones(contact)
        self.assertEqual(formatted[2]["value"], "# for texting")
        self.assertEqual([item["value"] for item in formatted], [
            "704-477-8603",
            "704-477-1359",
            "# for texting",
        ])


class HomePhoneSmsLinkTests(unittest.TestCase):
    def test_home_phone_variants_are_detected(self) -> None:
        self.assertTrue(_is_home_phone_type("Home"))
        self.assertTrue(_is_home_phone_type("home phone"))
        self.assertTrue(_is_home_phone_type("House"))
        self.assertFalse(_is_home_phone_type("Mobile"))
        self.assertFalse(_is_home_phone_type("Work"))

    def test_home_pdf_number_has_call_link_but_not_sms(self) -> None:
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
                                        "name": "HOME, Ann",
                                        "phones": [
                                            {"value": "7044778603", "code": "", "type": "Home"},
                                            {"value": "3363820709", "code": "c", "type": "Mobile"},
                                        ],
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
                    "font_family": "Arial",
                    "book_title": "Home SMS Book",
                },
                print_order_mode="alphabetical",
                print_order_json="",
            )
        finally:
            set_request_db_path(None)
            tempdir.cleanup()

        document = fitz.open(stream=pdf, filetype="pdf")
        try:
            uris = [str(link.get("uri") or "") for page in document for link in page.get_links()]
        finally:
            document.close()
        self.assertTrue(any("tel://7044778603" in uri for uri in uris))
        self.assertFalse(any("sms://" in uri and "7044778603" in uri for uri in uris))
        self.assertTrue(any("sms://3363820709" in uri for uri in uris))
