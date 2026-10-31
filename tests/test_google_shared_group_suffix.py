import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.database import apply_database_migrations, get_connection, initialize_database, set_request_db_path
from app.services.contact_service import build_contact_group_membership
from app.services.meeting_v2_service import ensure_default_book_layout_preset
from app.services.google_group_names import (
    has_google_shared_suffix,
    is_retired_catchall_group_name,
    normalize_group_membership_text,
    strip_google_shared_suffix,
    usable_shared_contacts_group_name,
)
from app.services.google_sync_service import (
    _desired_group_names,
    _ensure_contact_group_resource,
    _google_person_import_fields,
    _group_membership_text,
    _lookup_contact_group_resource,
    _parse_field_meeting,
    _parse_field_meeting_from_organizations,
    _shared_group_membership_names,
)


class StripGoogleSharedSuffixTests(unittest.TestCase):
    def test_tristate_separates_shared_suffix_is_stripped(self) -> None:
        self.assertEqual(strip_google_shared_suffix("TriState Separates (Shared)"), "TriState Separates")

    def test_meeting_label_salisbury_shared(self) -> None:
        self.assertEqual(strip_google_shared_suffix("Salisbury (Shared)"), "Salisbury")

    def test_case_and_spacing_variants(self) -> None:
        self.assertEqual(strip_google_shared_suffix("Salisbury (shared)"), "Salisbury")
        self.assertEqual(strip_google_shared_suffix("Salisbury(Shared)"), "Salisbury")
        self.assertEqual(strip_google_shared_suffix("Salisbury (SHARED) "), "Salisbury")

    def test_shared_in_the_middle_is_unchanged(self) -> None:
        self.assertEqual(strip_google_shared_suffix("AL Shared Harvest"), "AL Shared Harvest")
        self.assertEqual(strip_google_shared_suffix("Shared Harvest Meeting"), "Shared Harvest Meeting")
        self.assertEqual(strip_google_shared_suffix("Something (Shared Harvest)"), "Something (Shared Harvest)")

    def test_already_clean_name_is_unchanged(self) -> None:
        self.assertEqual(strip_google_shared_suffix("TriState Separates"), "TriState Separates")

    def test_has_google_shared_suffix_detects_trailing_only(self) -> None:
        self.assertTrue(has_google_shared_suffix("NC Eastern Field/Raleigh - APEX (Shared)"))
        self.assertTrue(has_google_shared_suffix("Salisbury(Shared)"))
        self.assertFalse(has_google_shared_suffix("NC Eastern Field/Raleigh - APEX"))
        self.assertFalse(has_google_shared_suffix("AL Shared Harvest"))

    def test_membership_merges_shared_duplicate_with_clean_name(self) -> None:
        self.assertEqual(
            normalize_group_membership_text(
                "AL Central - Salisbury (Shared):::AL Central - Salisbury:::myContacts"
            ),
            "AL Central - Salisbury:::myContacts",
        )

    def test_membership_drops_tristate_separates_catchall(self) -> None:
        self.assertEqual(
            normalize_group_membership_text(
                "AL Central - Salisbury:::TriState Separates (Shared):::TriState Separates:::myContacts"
            ),
            "AL Central - Salisbury:::myContacts",
        )
        self.assertEqual(
            normalize_group_membership_text(
                "TriState Separates (Shared):::TriState Separates:::myContacts"
            ),
            "myContacts",
        )
        self.assertNotIn(
            "TriState Separates",
            normalize_group_membership_text(
                "AL Central - Salisbury (Shared):::TriState Separates (Shared):::myContacts"
            ),
        )

    def test_retired_catchall_helper_matches_shared_and_clean(self) -> None:
        self.assertTrue(is_retired_catchall_group_name("TriState Separates (Shared)"))
        self.assertTrue(is_retired_catchall_group_name("TriState Separates"))
        self.assertFalse(is_retired_catchall_group_name("AL Central - Salisbury"))
        self.assertEqual(usable_shared_contacts_group_name("TriState Separates (Shared)"), "")
        self.assertEqual(usable_shared_contacts_group_name("AlMsLa (Shared)"), "AlMsLa")


class ParseGoogleSharedLabelTests(unittest.TestCase):
    def test_parse_field_meeting_from_shared_composite_label(self) -> None:
        field_name, meeting_name = _parse_field_meeting(
            ["TriState Separates (Shared)", "AL Central - Salisbury (Shared)", "myContacts"]
        )
        self.assertEqual(field_name, "AL Central")
        self.assertEqual(meeting_name, "Salisbury")

    def test_parse_standalone_tristate_label_is_not_a_field_meeting_pair(self) -> None:
        field_name, meeting_name = _parse_field_meeting(["TriState Separates (Shared)", "myContacts"])
        self.assertEqual(field_name, "")
        self.assertEqual(meeting_name, "")
        self.assertEqual(strip_google_shared_suffix("TriState Separates (Shared)"), "TriState Separates")

    def test_parse_meeting_from_organization_shared_suffix(self) -> None:
        field_name, meeting_name = _parse_field_meeting_from_organizations(
            [{"title": "AL Central (Shared)", "name": "Salisbury (Shared)"}]
        )
        self.assertEqual(field_name, "AL Central")
        self.assertEqual(meeting_name, "Salisbury")

    def test_import_fields_strip_shared_from_google_labels(self) -> None:
        fields = _google_person_import_fields(
            {
                "resourceName": "people/c1",
                "etag": "etag-1",
                "names": [{"givenName": "Jane", "familyName": "Doe"}],
                "memberships": [
                    {"contactGroupMembership": {"contactGroupResourceName": "contactGroups/1"}},
                    {"contactGroupMembership": {"contactGroupResourceName": "contactGroups/2"}},
                    {"contactGroupMembership": {"contactGroupResourceName": "contactGroups/myContacts"}},
                ],
            },
            {
                "contactGroups/1": "AL Central - Salisbury (Shared)",
                "contactGroups/2": "TriState Separates (Shared)",
                "contactGroups/myContacts": "myContacts",
            },
        )
        self.assertIsNotNone(fields)
        self.assertEqual(fields["fields_text"], "AL Central")
        self.assertEqual(fields["meetings_text"], "Salisbury")
        self.assertNotEqual(fields["fields_text"], "TriState Separates")
        with patch(
            "app.services.preset_service.get_shared_contacts_group_name",
            return_value="TriState Separates (Shared)",
        ):
            membership = _group_membership_text(
                _shared_group_membership_names(fields["fields_text"], fields["meetings_text"])
            )
        self.assertEqual(membership, "AL Central - Salisbury:::no field:::myContacts")
        self.assertNotIn("TriState Separates", membership)


class WriteGroupMembershipWithoutSharedTests(unittest.TestCase):
    def test_new_contact_membership_omits_tristate_catchall(self) -> None:
        with patch(
            "app.services.preset_service.get_shared_contacts_group_name",
            return_value="TriState Separates (Shared)",
        ):
            membership = build_contact_group_membership("AL Central", "Salisbury")
        self.assertEqual(membership, "AL Central - Salisbury:::no field:::myContacts")
        self.assertNotIn("TriState Separates", membership)
        self.assertNotIn("(Shared)", membership)

    def test_writing_strips_suffix_from_field_and_meeting(self) -> None:
        with patch(
            "app.services.preset_service.get_shared_contacts_group_name",
            return_value="",
        ):
            membership = build_contact_group_membership(
                "AL Central (Shared)",
                "Salisbury (Shared)",
            )
        self.assertEqual(membership, "AL Central - Salisbury:::no field:::myContacts")
        self.assertNotIn("(Shared)", membership)
        self.assertNotIn("TriState Separates", membership)

    def test_custom_catchall_from_settings_is_still_appended(self) -> None:
        with patch(
            "app.services.preset_service.get_shared_contacts_group_name",
            return_value="AlMsLa (Shared)",
        ):
            membership = build_contact_group_membership("AL Central", "Salisbury")
        self.assertEqual(membership, "AL Central - Salisbury:::no field:::AlMsLa:::myContacts")

    def test_google_upload_group_names_omit_tristate_catchall(self) -> None:
        with patch(
            "app.services.preset_service.get_shared_contacts_group_name",
            return_value="TriState Separates (Shared)",
        ):
            names = _shared_group_membership_names("AL Central", "Salisbury (Shared)")
        self.assertEqual(names, ["AL Central - Salisbury", "no field", "myContacts"])
        self.assertNotIn("TriState Separates", names)
        self.assertFalse(any("(Shared)" in name for name in names))

    def test_desired_groups_drop_catchall_leftovers(self) -> None:
        with patch(
            "app.services.preset_service.get_shared_contacts_group_name",
            return_value="TriState Separates",
        ):
            names = _desired_group_names(
                {
                    "fields_text": "AL Central",
                    "meetings_text": "Salisbury",
                    "group_membership": (
                        "AL Central - Salisbury:::TriState Separates:::TriState Separates (Shared):::myContacts"
                    ),
                }
            )
        self.assertEqual(names, ["AL Central - Salisbury", "no field", "myContacts"])
        self.assertNotIn("TriState Separates", names)

    def test_desired_groups_never_include_shared_suffix(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            names = _desired_group_names(
                {
                    "fields_text": "NC Eastern Field/Raleigh",
                    "meetings_text": "APEX",
                    "group_membership": (
                        "NC Eastern Field/Raleigh - APEX (Shared):::NCcfs:::myContacts"
                    ),
                }
            )
        self.assertEqual(names, ["NC Eastern Field/Raleigh - APEX", "NCcfs", "myContacts"])
        self.assertFalse(any(has_google_shared_suffix(name) for name in names))
        self.assertFalse(any(name.endswith("(Shared)") for name in names))

    def test_lookup_prefers_clean_group_when_shared_duplicate_exists(self) -> None:
        resource_to_name = {
            "contactGroups/shared": "AL Central - Salisbury (Shared)",
            "contactGroups/clean": "AL Central - Salisbury",
        }
        name_to_resource = {
            "AL Central - Salisbury (Shared)": "contactGroups/shared",
            "AL Central - Salisbury": "contactGroups/clean",
        }
        self.assertEqual(
            _lookup_contact_group_resource(
                "AL Central - Salisbury (Shared)", name_to_resource, resource_to_name
            ),
            "contactGroups/clean",
        )
        self.assertEqual(
            _lookup_contact_group_resource("AL Central - Salisbury", name_to_resource, resource_to_name),
            "contactGroups/clean",
        )

    def test_lookup_does_not_reuse_shared_twin_for_clean_name(self) -> None:
        resource_to_name = {"contactGroups/shared": "AL Central - Salisbury (Shared)"}
        name_to_resource = {
            "AL Central - Salisbury (Shared)": "contactGroups/shared",
            "AL Central - Salisbury": "contactGroups/shared",
        }
        self.assertEqual(
            _lookup_contact_group_resource("AL Central - Salisbury", name_to_resource, resource_to_name),
            "",
        )

    def test_lookup_does_not_resolve_apex_shared_as_clean_field_meeting(self) -> None:
        resource_to_name = {
            "contactGroups/shared": "NC Eastern Field/Raleigh - APEX (Shared)",
            "contactGroups/region": "NCcfs",
        }
        name_to_resource = {
            "NC Eastern Field/Raleigh - APEX (Shared)": "contactGroups/shared",
            "NC Eastern Field/Raleigh - APEX": "contactGroups/shared",
            "NCcfs": "contactGroups/region",
        }
        self.assertEqual(
            _lookup_contact_group_resource(
                "NC Eastern Field/Raleigh - APEX", name_to_resource, resource_to_name
            ),
            "",
        )
        self.assertEqual(
            _lookup_contact_group_resource("NCcfs", name_to_resource, resource_to_name),
            "contactGroups/region",
        )

    def test_ensure_creates_clean_group_when_only_shared_twin_exists(self) -> None:
        resource_to_name = {
            "contactGroups/shared": "NC Eastern Field/Raleigh - APEX (Shared)",
        }
        name_to_resource = {
            "NC Eastern Field/Raleigh - APEX (Shared)": "contactGroups/shared",
            "NC Eastern Field/Raleigh - APEX": "contactGroups/shared",
        }
        with patch(
            "app.services.google_sync_service._api_json_request",
            return_value={
                "resourceName": "contactGroups/clean",
                "name": "NC Eastern Field/Raleigh - APEX",
                "formattedName": "NC Eastern Field/Raleigh - APEX",
            },
        ) as create_group:
            resource = _ensure_contact_group_resource(
                "token",
                "NC Eastern Field/Raleigh - APEX",
                name_to_resource,
                resource_to_name,
            )
        self.assertEqual(resource, "contactGroups/clean")
        create_group.assert_called_once()
        self.assertEqual(
            resource_to_name["contactGroups/clean"],
            "NC Eastern Field/Raleigh - APEX",
        )
        self.assertNotEqual(
            _lookup_contact_group_resource(
                "NC Eastern Field/Raleigh - APEX", name_to_resource, resource_to_name
            ),
            "contactGroups/shared",
        )


class StoredSharedSuffixMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self._tempdir.name) / "app.sqlite3")
        initialize_database()
        ensure_default_book_layout_preset()

    def tearDown(self) -> None:
        set_request_db_path(None)
        self._tempdir.cleanup()

    def test_startup_migration_strips_existing_contact_rows(self) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO contacts (
                  family_name, given_name, fields_text, meetings_text, group_membership
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "Doe",
                    "Jane",
                    "TriState Separates (Shared)",
                    "Salisbury (Shared)",
                    "AL Central - Salisbury (Shared):::TriState Separates (Shared):::TriState Separates:::myContacts",
                ),
            )
            conn.execute(
                """
                INSERT INTO contacts (
                  family_name, given_name, fields_text, meetings_text, group_membership
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "Roe",
                    "John",
                    "AL Central",
                    "Salisbury",
                    "AL Central - Salisbury:::TriState Separates:::myContacts",
                ),
            )
            conn.execute(
                """
                INSERT INTO contact_assignment_options (kind, value)
                VALUES ('field', 'TriState Separates (Shared)'), ('meeting', 'Salisbury (Shared)'),
                       ('field', 'AL Central (Shared)')
                """
            )
            conn.execute(
                """
                UPDATE book_layout_presets
                SET shared_contacts_group_name = 'TriState Separates (Shared)'
                WHERE is_default = 1
                """
            )
            conn.commit()

        apply_database_migrations()

        with get_connection() as conn:
            contacts = [
                dict(row)
                for row in conn.execute(
                    "SELECT family_name, fields_text, meetings_text, group_membership FROM contacts ORDER BY id"
                ).fetchall()
            ]
            jane = contacts[0]
            john = contacts[1]
            self.assertEqual(jane["fields_text"], "AL Central")
            self.assertEqual(jane["meetings_text"], "Salisbury")
            self.assertEqual(jane["group_membership"], "AL Central - Salisbury:::no field:::myContacts")
            self.assertNotIn("TriState Separates", jane["group_membership"])
            self.assertNotIn("(Shared)", jane["group_membership"])
            self.assertEqual(john["fields_text"], "AL Central")
            self.assertEqual(john["meetings_text"], "Salisbury")
            self.assertEqual(john["group_membership"], "AL Central - Salisbury:::no field:::myContacts")
            self.assertNotIn("TriState Separates", john["group_membership"])
            option_values = {
                str(row["value"])
                for row in conn.execute("SELECT value FROM contact_assignment_options").fetchall()
            }
            self.assertIn("Salisbury", option_values)
            self.assertIn("AL Central", option_values)
            self.assertNotIn("TriState Separates", option_values)
            self.assertNotIn("TriState Separates (Shared)", option_values)
            self.assertNotIn("Salisbury (Shared)", option_values)
            self.assertNotIn("AL Central (Shared)", option_values)
            preset = dict(
                conn.execute(
                    "SELECT shared_contacts_group_name FROM book_layout_presets WHERE is_default = 1"
                ).fetchone()
            )
            self.assertEqual(preset["shared_contacts_group_name"], "")


if __name__ == "__main__":
    unittest.main()
