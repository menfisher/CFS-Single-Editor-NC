import unittest

from app.services.app_info_service import (
    MULTI_EDITOR_EDITION,
    SINGLE_EDITOR_EDITION,
    SINGLE_EDITOR_UPDATE_MANIFEST_URL,
    get_app_edition,
    get_expected_update_manifest_url,
    update_manifest_url_matches_edition,
)


class AppEditionTests(unittest.TestCase):
    def test_this_app_is_single_editor(self) -> None:
        self.assertEqual(get_app_edition(), SINGLE_EDITOR_EDITION)

    def test_expected_feed_is_single_editor_nc(self) -> None:
        self.assertEqual(
            get_expected_update_manifest_url(),
            "https://menfisher.github.io/contactsfreeshare-se-nc-updates/app_update_manifest.json",
        )
        self.assertEqual(SINGLE_EDITOR_UPDATE_MANIFEST_URL, get_expected_update_manifest_url())

    def test_single_editor_nc_url_is_accepted_for_single_editor(self) -> None:
        self.assertTrue(
            update_manifest_url_matches_edition(
                "https://menfisher.github.io/contactsfreeshare-se-nc-updates/app_update_manifest.json",
                SINGLE_EDITOR_EDITION,
            )
        )

    def test_shared_single_editor_url_is_rejected_for_this_app(self) -> None:
        self.assertFalse(
            update_manifest_url_matches_edition(
                "https://menfisher.github.io/contactsfreeshare-se-updates/app_update_manifest.json",
                SINGLE_EDITOR_EDITION,
            )
        )

    def test_multi_editor_url_is_rejected_for_single_editor(self) -> None:
        self.assertFalse(
            update_manifest_url_matches_edition(
                "https://menfisher.github.io/contactsfreeshare-updates/app_update_manifest.json",
                SINGLE_EDITOR_EDITION,
            )
        )

    def test_single_editor_nc_url_is_rejected_for_multi_editor(self) -> None:
        self.assertFalse(
            update_manifest_url_matches_edition(
                "https://menfisher.github.io/contactsfreeshare-se-nc-updates/app_update_manifest.json",
                MULTI_EDITOR_EDITION,
            )
        )


if __name__ == "__main__":
    unittest.main()
