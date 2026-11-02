import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.database import apply_database_migrations, get_connection, initialize_database, set_request_db_path
from app.services.contact_service import build_contact_group_membership, create_contact, move_contacts
from app.services.google_group_names import has_google_shared_suffix, parse_field_meeting_from_group_names
from app.services.google_sync_service import _desired_group_names, _shared_group_membership_names
from app.services.meeting_v2_service import ensure_default_book_layout_preset
from app.services.region_group_names import (
    REGION_GROUP_NCCFS,
    REGION_GROUP_NO_FIELD,
    REGION_GROUP_SCCFS,
    REGION_GROUP_VACFS,
    contact_group_membership_names,
    infer_region_from_label_texts,
    region_group_name_for_contact,
    region_group_name_for_field,
)


class RegionGroupNameMapTests(unittest.TestCase):
    def test_nc_fields_map_to_nccfs(self) -> None:
        self.assertEqual(region_group_name_for_field("NC Eastern Field/Raleigh"), REGION_GROUP_NCCFS)
        self.assertEqual(region_group_name_for_field("NC Central Field/Greensboro"), REGION_GROUP_NCCFS)
        self.assertEqual(region_group_name_for_field("NC Western Field/Charlotte"), REGION_GROUP_NCCFS)
        self.assertEqual(region_group_name_for_field("NC15 Not Printed"), REGION_GROUP_NCCFS)
        self.assertEqual(region_group_name_for_field("NC Workers"), REGION_GROUP_NCCFS)
        self.assertEqual(region_group_name_for_field("NC Central & South SC"), REGION_GROUP_NCCFS)
        self.assertEqual(region_group_name_for_field("NC Northwest SC"), REGION_GROUP_NCCFS)
        self.assertEqual(region_group_name_for_field("FL GA SC Workers"), REGION_GROUP_NCCFS)
        self.assertEqual(region_group_name_for_field("NC Not Printed"), REGION_GROUP_NCCFS)

    def test_south_carolina_field_maps_to_sccfs(self) -> None:
        self.assertEqual(region_group_name_for_field("  South Carolina  "), REGION_GROUP_SCCFS)
        self.assertEqual(region_group_name_for_field("South Carolina"), REGION_GROUP_SCCFS)

    def test_va_fields_map_to_vacfs(self) -> None:
        self.assertEqual(region_group_name_for_field("Maryland and Delaware"), REGION_GROUP_VACFS)
        self.assertEqual(region_group_name_for_field("Southeast Virginia"), REGION_GROUP_VACFS)
        self.assertEqual(region_group_name_for_field("Western Virginia"), REGION_GROUP_VACFS)
        self.assertEqual(
            region_group_name_for_field("Northern Virginia and Fredericksburg"),
            REGION_GROUP_VACFS,
        )
        self.assertEqual(region_group_name_for_field("Other Contacts"), REGION_GROUP_VACFS)

    def test_empty_field_maps_to_vacfs(self) -> None:
        self.assertEqual(region_group_name_for_field(""), REGION_GROUP_VACFS)
        self.assertEqual(region_group_name_for_field("   "), REGION_GROUP_VACFS)

    def test_unmatched_named_field_maps_to_no_field(self) -> None:
        self.assertEqual(region_group_name_for_field("AL Central"), REGION_GROUP_NO_FIELD)

    def test_four_digit_year_maps_to_nccfs(self) -> None:
        self.assertEqual(region_group_name_for_field("2026"), REGION_GROUP_NCCFS)
        self.assertEqual(region_group_name_for_field("2027"), REGION_GROUP_NCCFS)
        self.assertEqual(region_group_name_for_field("1999"), REGION_GROUP_NCCFS)
        self.assertEqual(region_group_name_for_field("26"), REGION_GROUP_NO_FIELD)


class VirginiaAndNcLabelRegionTests(unittest.TestCase):
    def test_virginia_in_label_is_vacfs_without_va_token(self) -> None:
        self.assertEqual(
            infer_region_from_label_texts(["Southeast Virginia - SANDSTON"]),
            REGION_GROUP_VACFS,
        )
        self.assertEqual(
            infer_region_from_label_texts(["Western Virginia - CHARLOTTESVILLE"]),
            REGION_GROUP_VACFS,
        )
        self.assertEqual(
            infer_region_from_label_texts(
                ["Northern Virginia and Fredericksburg - FALLS CHURCH (Shared)"]
            ),
            REGION_GROUP_VACFS,
        )

    def test_va_token_and_paren_are_vacfs(self) -> None:
        self.assertEqual(
            infer_region_from_label_texts(["CHARLOTTESVILLE, VA"]),
            REGION_GROUP_VACFS,
        )
        self.assertEqual(infer_region_from_label_texts(["(VA) Richmond"]), REGION_GROUP_VACFS)

    def test_nc_in_field_meeting_label_is_nccfs(self) -> None:
        self.assertEqual(
            infer_region_from_label_texts(["NC Eastern Field/Raleigh - APEX (Shared)"]),
            REGION_GROUP_NCCFS,
        )
        self.assertEqual(infer_region_from_label_texts(["NC15 Not Printed - Moved"]), REGION_GROUP_NCCFS)
        self.assertEqual(infer_region_from_label_texts(["NC Workers"]), REGION_GROUP_NCCFS)

    def test_south_carolina_labels_are_sccfs(self) -> None:
        self.assertEqual(
            infer_region_from_label_texts(["South Carolina - CHARLESTON"]),
            REGION_GROUP_SCCFS,
        )
        self.assertEqual(
            infer_region_from_label_texts(["South Carolina - CHARLESTON (Shared)"]),
            REGION_GROUP_SCCFS,
        )

    def test_nc_named_south_carolina_fields_stay_nccfs(self) -> None:
        self.assertEqual(
            infer_region_from_label_texts(["NC Central & South SC - SUMTER (Shared)"]),
            REGION_GROUP_NCCFS,
        )
        self.assertEqual(
            infer_region_from_label_texts(["NC Northwest SC - SPARTANBURG"]),
            REGION_GROUP_NCCFS,
        )
        self.assertEqual(infer_region_from_label_texts(["FL GA SC Workers"]), REGION_GROUP_NCCFS)

    def test_contacts_and_nova_are_not_false_positives(self) -> None:
        self.assertEqual(infer_region_from_label_texts(["CONTACTS, Raleigh Field"]), "")
        self.assertEqual(infer_region_from_label_texts(["NoVA Contacts"]), "")
        self.assertEqual(infer_region_from_label_texts(["AL Shared Harvest"]), "")

    def test_tristate_is_ignored(self) -> None:
        self.assertEqual(
            infer_region_from_label_texts(
                ["TriState Separates (Shared)", "TriState Separates"]
            ),
            "",
        )

    def test_field_meeting_label_wins_over_tristate(self) -> None:
        self.assertEqual(
            infer_region_from_label_texts(
                [
                    "TriState Separates (Shared)",
                    "Southeast Virginia - SANDSTON (Shared)",
                ]
            ),
            REGION_GROUP_VACFS,
        )

    def test_empty_field_uses_label_instead_of_default_only(self) -> None:
        self.assertEqual(region_group_name_for_field(""), REGION_GROUP_VACFS)
        self.assertEqual(
            region_group_name_for_contact(
                "",
                "",
                extra_labels=["Western Virginia - LEXINGTON (Shared)"],
                parsed_field="Western Virginia",
            ),
            REGION_GROUP_VACFS,
        )
        self.assertEqual(
            region_group_name_for_contact(
                "",
                "",
                extra_labels=["South Carolina - CHARLESTON (Shared)"],
                parsed_field="South Carolina",
            ),
            REGION_GROUP_SCCFS,
        )

    def test_hardcoded_field_map_still_wins(self) -> None:
        self.assertEqual(
            region_group_name_for_contact(
                "Western Virginia",
                "CHARLOTTESVILLE, VA",
                extra_labels=["NC Eastern Field/Raleigh - APEX (Shared)"],
            ),
            REGION_GROUP_VACFS,
        )
        self.assertEqual(
            region_group_name_for_contact("AL Central", "Salisbury"),
            REGION_GROUP_NO_FIELD,
        )


class RegionGroupBuilderTests(unittest.TestCase):
    def test_nc_field_meeting_order(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            membership = build_contact_group_membership("NC Eastern Field/Raleigh", "APEX")
        self.assertEqual(membership, "NC Eastern Field/Raleigh - APEX:::NCcfs:::myContacts")
        self.assertNotIn("TriState", membership)
        self.assertNotIn("VAcfs", membership)

    def test_va_field_meeting_order(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            membership = build_contact_group_membership("Western Virginia", "CHARLOTTESVILLE, VA")
        self.assertEqual(membership, "Western Virginia - CHARLOTTESVILLE, VA:::VAcfs:::myContacts")

    def test_empty_field_is_vacfs(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            membership = build_contact_group_membership("", "")
        self.assertEqual(membership, "VAcfs:::myContacts")

    def test_missing_meeting_omits_pair_keeps_region(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            membership = build_contact_group_membership("NC Eastern Field/Raleigh", "")
        self.assertEqual(membership, "NCcfs:::myContacts")

    def test_year_deleted_is_nccfs(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            membership = build_contact_group_membership("2026", "Deleted")
        self.assertEqual(membership, "2026 - Deleted:::NCcfs:::myContacts")

    def test_future_year_is_nccfs(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            membership = build_contact_group_membership("2027", "Deleted")
        self.assertEqual(membership, "2027 - Deleted:::NCcfs:::myContacts")

    def test_shared_helper_matches_builder(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            names = _shared_group_membership_names("NC Eastern Field/Raleigh", "APEX")
            membership = build_contact_group_membership("NC Eastern Field/Raleigh", "APEX")
        self.assertEqual(":::".join(names), membership)

    def test_builder_never_includes_tristate(self) -> None:
        with patch(
            "app.services.preset_service.get_shared_contacts_group_name",
            return_value="TriState Separates (Shared)",
        ):
            membership = build_contact_group_membership("NC Eastern Field/Raleigh", "APEX")
        self.assertEqual(membership, "NC Eastern Field/Raleigh - APEX:::NCcfs:::myContacts")
        self.assertNotIn("TriState", membership)
        self.assertNotIn("(Shared)", membership)


class DesiredRegionGroupTests(unittest.TestCase):
    def test_desired_groups_never_keep_both_region_tokens(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            names = _desired_group_names(
                {
                    "fields_text": "Western Virginia",
                    "meetings_text": "CHARLOTTESVILLE, VA",
                    "group_membership": (
                        "Western Virginia - CHARLOTTESVILLE, VA:::NCcfs:::VAcfs:::no field:::myContacts"
                    ),
                }
            )
        self.assertEqual(
            names,
            ["Western Virginia - CHARLOTTESVILLE, VA", "VAcfs", "myContacts"],
        )
        self.assertNotIn("NCcfs", names)
        self.assertNotIn("no field", names)

    def test_desired_groups_drop_tristate_and_use_region(self) -> None:
        with patch(
            "app.services.preset_service.get_shared_contacts_group_name",
            return_value="TriState Separates",
        ):
            names = _desired_group_names(
                {
                    "fields_text": "NC Eastern Field/Raleigh",
                    "meetings_text": "APEX",
                    "group_membership": (
                        "NC Eastern Field/Raleigh - APEX:::TriState Separates:::myContacts"
                    ),
                }
            )
        self.assertEqual(names, ["NC Eastern Field/Raleigh - APEX", "NCcfs", "myContacts"])
        self.assertNotIn("TriState Separates", names)

    def test_empty_field_desired_is_vacfs(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            names = _desired_group_names(
                {
                    "fields_text": "",
                    "meetings_text": "",
                    "group_membership": "NCcfs:::VAcfs:::no field:::myContacts",
                }
            )
        self.assertEqual(names, ["VAcfs", "myContacts"])
        self.assertNotIn("NCcfs", names)
        self.assertNotIn("no field", names)

    def test_empty_field_rebuilds_clean_membership_from_shared_label(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            names = contact_group_membership_names(
                "",
                "",
                extra_labels=[
                    "NC Eastern Field/Raleigh - APEX (Shared)",
                    "TriState Separates (Shared)",
                    "myContacts",
                ],
            )
        self.assertEqual(names, ["NC Eastern Field/Raleigh - APEX", "NCcfs", "myContacts"])
        self.assertNotIn("TriState Separates", names)
        self.assertFalse(any(has_google_shared_suffix(name) for name in names))

    def test_empty_field_rebuilds_sccfs_from_south_carolina_label(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            names = contact_group_membership_names(
                "",
                "",
                extra_labels=[
                    "South Carolina - CHARLESTON (Shared)",
                    "TriState Separates (Shared)",
                    "myContacts",
                ],
            )
        self.assertEqual(names, ["South Carolina - CHARLESTON", "SCcfs", "myContacts"])
        self.assertNotIn("NCcfs", names)
        self.assertNotIn("VAcfs", names)

    def test_desired_groups_never_include_tristate_or_shared_suffix(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            names = _desired_group_names(
                {
                    "fields_text": "",
                    "meetings_text": "",
                    "group_membership": (
                        "NC Eastern Field/Raleigh - APEX (Shared):::"
                        "TriState Separates (Shared):::myContacts"
                    ),
                },
                extra_group_titles=["NC Eastern Field/Raleigh - APEX (Shared)"],
            )
        self.assertEqual(names, ["NC Eastern Field/Raleigh - APEX", "NCcfs", "myContacts"])
        self.assertNotIn("TriState Separates", names)
        self.assertFalse(any(name.endswith("(Shared)") for name in names))


class RegionLabelParseTests(unittest.TestCase):
    def test_south_carolina_builder_is_sccfs(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            membership = build_contact_group_membership("South Carolina", "CHARLESTON")
        self.assertEqual(membership, "South Carolina - CHARLESTON:::SCcfs:::myContacts")
        self.assertNotIn("NCcfs", membership)
        self.assertNotIn("VAcfs", membership)

    def test_region_labels_are_not_parsed_as_field_meeting(self) -> None:
        field_name, meeting_name = parse_field_meeting_from_group_names(
            ["NCcfs", "VAcfs", "SCcfs", "no field", "myContacts"]
        )
        self.assertEqual(field_name, "")
        self.assertEqual(meeting_name, "")

    def test_round_trip_keeps_field_meeting_and_region(self) -> None:
        field_name, meeting_name = parse_field_meeting_from_group_names(
            ["NC Eastern Field/Raleigh - APEX", "NCcfs", "myContacts"]
        )
        self.assertEqual(field_name, "NC Eastern Field/Raleigh")
        self.assertEqual(meeting_name, "APEX")
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            membership = build_contact_group_membership(field_name, meeting_name)
        self.assertEqual(membership, "NC Eastern Field/Raleigh - APEX:::NCcfs:::myContacts")


class RegionGroupMoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self._tempdir.name) / "app.sqlite3")
        initialize_database()
        ensure_default_book_layout_preset()

    def tearDown(self) -> None:
        set_request_db_path(None)
        self._tempdir.cleanup()

    def test_move_switches_nccfs_to_vacfs(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            contact_id = create_contact(
                {
                    "family_name": "Doe",
                    "given_name": "Jane",
                    "fields_text": "NC Eastern Field/Raleigh",
                    "meetings_text": "APEX",
                }
            )
            with get_connection() as conn:
                before = dict(
                    conn.execute(
                        "SELECT group_membership FROM contacts WHERE id = ?",
                        (contact_id,),
                    ).fetchone()
                )
            self.assertEqual(before["group_membership"], "NC Eastern Field/Raleigh - APEX:::NCcfs:::myContacts")
            moved = move_contacts([contact_id], "Western Virginia", "CHARLOTTESVILLE, VA")
            self.assertEqual(moved, 1)
            with get_connection() as conn:
                after = dict(
                    conn.execute(
                        "SELECT fields_text, meetings_text, group_membership FROM contacts WHERE id = ?",
                        (contact_id,),
                    ).fetchone()
                )
        self.assertEqual(after["fields_text"], "Western Virginia")
        self.assertEqual(after["meetings_text"], "CHARLOTTESVILLE, VA")
        self.assertEqual(
            after["group_membership"],
            "Western Virginia - CHARLOTTESVILLE, VA:::VAcfs:::myContacts",
        )
        self.assertNotIn("NCcfs", after["group_membership"])

    def test_move_to_empty_field_uses_vacfs(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            contact_id = create_contact(
                {
                    "family_name": "Roe",
                    "given_name": "John",
                    "fields_text": "Western Virginia",
                    "meetings_text": "CHARLOTTESVILLE, VA",
                }
            )
            move_contacts([contact_id], "", "")
            with get_connection() as conn:
                after = dict(
                    conn.execute(
                        "SELECT group_membership FROM contacts WHERE id = ?",
                        (contact_id,),
                    ).fetchone()
                )
        self.assertEqual(after["group_membership"], "VAcfs:::myContacts")

    def test_same_field_meeting_move_rebuilds_membership_and_queues(self) -> None:
        with patch("app.services.preset_service.get_shared_contacts_group_name", return_value=""):
            with get_connection() as conn:
                conn.execute("UPDATE google_sync_state SET sync_enabled = 1 WHERE id = 1")
                conn.execute(
                    """
                    INSERT INTO contacts (
                      family_name, given_name, google_contact_id, fields_text, meetings_text, group_membership
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "MacCallum",
                        "Kevin",
                        "people/kevin",
                        "NC Eastern Field/Raleigh",
                        "APEX",
                        "NC Eastern Field/Raleigh - APEX (Shared):::myContacts",
                    ),
                )
                conn.commit()
                contact_id = int(conn.execute("SELECT id FROM contacts").fetchone()["id"])

            moved = move_contacts([contact_id], "NC Eastern Field/Raleigh", "APEX")
            self.assertEqual(moved, 1)
            with get_connection() as conn:
                after = dict(
                    conn.execute(
                        "SELECT fields_text, meetings_text, group_membership FROM contacts WHERE id = ?",
                        (contact_id,),
                    ).fetchone()
                )
                queued = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT contact_id, operation, payload_json, status
                        FROM google_sync_queue
                        WHERE status = 'pending'
                        ORDER BY contact_id
                        """
                    ).fetchall()
                ]

        self.assertEqual(after["fields_text"], "NC Eastern Field/Raleigh")
        self.assertEqual(after["meetings_text"], "APEX")
        self.assertEqual(
            after["group_membership"],
            "NC Eastern Field/Raleigh - APEX:::NCcfs:::myContacts",
        )
        self.assertNotIn("(Shared)", after["group_membership"])
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["operation"], "update")
        payload = json.loads(queued[0]["payload_json"])
        self.assertEqual(payload["sync_action"], "Move")
        self.assertEqual(
            payload["group_membership"],
            "NC Eastern Field/Raleigh - APEX:::NCcfs:::myContacts",
        )
        self.assertNotIn("(Shared)", payload["group_membership"])


class RegionGroupStartupRewriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self._tempdir.name) / "app.sqlite3")
        initialize_database()
        ensure_default_book_layout_preset()

    def tearDown(self) -> None:
        set_request_db_path(None)
        self._tempdir.cleanup()

    def test_startup_rebuilds_membership_and_queues_changed_contacts(self) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE google_sync_state SET sync_enabled = 1 WHERE id = 1")
            conn.execute(
                """
                INSERT INTO contacts (
                  family_name, given_name, google_contact_id, fields_text, meetings_text, group_membership
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "One",
                    "NC",
                    "people/c-nc",
                    "NC Eastern Field/Raleigh",
                    "APEX",
                    "NC Eastern Field/Raleigh - APEX:::myContacts",
                ),
            )
            conn.execute(
                """
                INSERT INTO contacts (
                  family_name, given_name, google_contact_id, fields_text, meetings_text, group_membership
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "Two",
                    "VA",
                    "people/c-va",
                    "Western Virginia",
                    "CHARLOTTESVILLE, VA",
                    "Western Virginia - CHARLOTTESVILLE, VA:::myContacts",
                ),
            )
            conn.execute(
                """
                INSERT INTO contacts (
                  family_name, given_name, google_contact_id, fields_text, meetings_text, group_membership
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("Three", "Empty", "people/c-empty", "", "", "myContacts"),
            )
            conn.execute(
                """
                INSERT INTO contacts (
                  family_name, given_name, google_contact_id, fields_text, meetings_text, group_membership
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "Four",
                    "Year",
                    "people/c-year",
                    "2026",
                    "Deleted",
                    "2026 - Deleted:::myContacts",
                ),
            )
            conn.commit()

        apply_database_migrations()

        with get_connection() as conn:
            rows = {
                str(row["family_name"]): dict(row)
                for row in conn.execute(
                    "SELECT family_name, group_membership FROM contacts ORDER BY id"
                ).fetchall()
            }
            self.assertEqual(
                rows["One"]["group_membership"],
                "NC Eastern Field/Raleigh - APEX:::NCcfs:::myContacts",
            )
            self.assertEqual(
                rows["Two"]["group_membership"],
                "Western Virginia - CHARLOTTESVILLE, VA:::VAcfs:::myContacts",
            )
            self.assertEqual(rows["Three"]["group_membership"], "VAcfs:::myContacts")
            self.assertEqual(rows["Four"]["group_membership"], "2026 - Deleted:::NCcfs:::myContacts")

            queued = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT contact_id, operation, payload_json, status
                    FROM google_sync_queue
                    WHERE status = 'pending'
                    ORDER BY contact_id
                    """
                ).fetchall()
            ]
            self.assertEqual(len(queued), 4)
            self.assertTrue(all(item["operation"] == "update" for item in queued))
            payloads = [json.loads(item["payload_json"]) for item in queued]
            self.assertEqual(
                {item["group_membership"] for item in payloads},
                {
                    "NC Eastern Field/Raleigh - APEX:::NCcfs:::myContacts",
                    "Western Virginia - CHARLOTTESVILLE, VA:::VAcfs:::myContacts",
                    "VAcfs:::myContacts",
                    "2026 - Deleted:::NCcfs:::myContacts",
                },
            )
            self.assertTrue(all(item["sync_action"] == "Move" for item in payloads))

        apply_database_migrations()
        with get_connection() as conn:
            queued_again = conn.execute(
                "SELECT COUNT(*) AS count FROM google_sync_queue WHERE status = 'pending'"
            ).fetchone()["count"]
        self.assertEqual(queued_again, 4)

    def test_rebuild_south_carolina_becomes_sccfs_without_queueing_everyone(self) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE google_sync_state SET sync_enabled = 1 WHERE id = 1")
            conn.execute(
                """
                INSERT INTO contacts (
                  family_name, given_name, google_contact_id, fields_text, meetings_text, group_membership
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "Carolina",
                    "South",
                    "people/c-sc",
                    "South Carolina",
                    "CHARLESTON",
                    "South Carolina - CHARLESTON:::NCcfs:::myContacts",
                ),
            )
            conn.execute(
                """
                INSERT INTO contacts (
                  family_name, given_name, google_contact_id, fields_text, meetings_text, group_membership
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "Already",
                    "NC",
                    "people/c-nc",
                    "NC Eastern Field/Raleigh",
                    "APEX",
                    "NC Eastern Field/Raleigh - APEX:::NCcfs:::myContacts",
                ),
            )
            conn.commit()

        apply_database_migrations()

        with get_connection() as conn:
            rows = {
                str(row["family_name"]): dict(row)
                for row in conn.execute(
                    "SELECT family_name, group_membership FROM contacts ORDER BY id"
                ).fetchall()
            }
            self.assertEqual(
                rows["Carolina"]["group_membership"],
                "South Carolina - CHARLESTON:::SCcfs:::myContacts",
            )
            self.assertEqual(
                rows["Already"]["group_membership"],
                "NC Eastern Field/Raleigh - APEX:::NCcfs:::myContacts",
            )
            queued = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT google_contact_id, payload_json
                    FROM google_sync_queue
                    WHERE status = 'pending'
                    ORDER BY id
                    """
                ).fetchall()
            ]
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["google_contact_id"], "people/c-sc")
        self.assertEqual(
            json.loads(queued[0]["payload_json"])["group_membership"],
            "South Carolina - CHARLESTON:::SCcfs:::myContacts",
        )

    def test_rebuild_persists_region_from_stored_virginia_membership(self) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE google_sync_state SET sync_enabled = 1 WHERE id = 1")
            conn.execute(
                """
                INSERT INTO contacts (
                  family_name, given_name, google_contact_id, fields_text, meetings_text, group_membership
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "Empty",
                    "VA",
                    "people/c-va-empty",
                    "",
                    "",
                    "Southeast Virginia - SANDSTON (Shared):::TriState Separates (Shared):::myContacts",
                ),
            )
            conn.commit()

        apply_database_migrations()
        with get_connection() as conn:
            row = dict(
                conn.execute(
                    "SELECT group_membership FROM contacts WHERE google_contact_id = ?",
                    ("people/c-va-empty",),
                ).fetchone()
            )
            queued = conn.execute(
                "SELECT COUNT(*) AS count FROM google_sync_queue WHERE status = 'pending'"
            ).fetchone()["count"]
        self.assertEqual(row["group_membership"], "Southeast Virginia - SANDSTON:::VAcfs:::myContacts")
        self.assertNotIn("TriState", row["group_membership"])
        self.assertNotIn("(Shared)", row["group_membership"])
        self.assertEqual(queued, 1)


if __name__ == "__main__":
    unittest.main()
