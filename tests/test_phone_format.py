import tempfile
import unittest
from pathlib import Path

from app.database import initialize_database, set_request_db_path
from app.services.contact_service import create_contact, get_contact_detail
from app.services.field_list_service import (
    _field_list_contact_payload,
    _format_contact_phones,
    _is_blank_phone_type,
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

    def test_blank_phone_column_text_is_clipped_to_12_characters(self) -> None:
        phones = _format_contact_phones(
            {
                "given_name": "Ada",
                "phones": [
                    {"phone_type": "Blank", "phone_value": "123456789012345"},
                    {"phone_type": "Mobile", "phone_value": "704-965-6271 x999"},
                ],
            }
        )
        self.assertEqual(phones[0]["value"], "123456789012")
        self.assertEqual(len(phones[0]["value"]), 12)
        self.assertEqual(phones[1]["value"], "704-965-6271 x999")


class PhonePrintOrderTests(unittest.TestCase):
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
                "phone_type": ["Work", "Blank", "Mobile"],
                "phone_value": ["999-000-1111", "see notes inside", "111-222-3333"],
                "phone_code": ["", "S", ""],
            }
        )
        contact = get_contact_detail(contact_id)
        self.assertIsNotNone(contact)
        phones = contact["phones"]
        self.assertEqual(
            [(item["phone_type"], item["phone_value"], item.get("phone_code") or "") for item in phones],
            [
                ("Work", "999-000-1111", ""),
                ("Blank", "see notes in", "S"),
                ("Mobile", "111-222-3333", ""),
            ],
        )
        formatted = _format_contact_phones(contact)
        self.assertEqual(formatted[1]["value"], "see notes in")
        self.assertEqual(formatted[1]["code"], "S")
        self.assertEqual([item["value"] for item in formatted], [
            "999-000-1111",
            "see notes in",
            "111-222-3333",
        ])
