import unittest

from app.config import _merge_env_values


class PackagedEnvTests(unittest.TestCase):
    def test_blank_env_values_do_not_hide_packaged_google_settings(self) -> None:
        merged = _merge_env_values(
            [
                {
                    "GOOGLE_OAUTH_CLIENT_ID": "packaged-client",
                    "GOOGLE_OAUTH_CLIENT_SECRET": "packaged-secret",
                },
                {
                    "GOOGLE_OAUTH_CLIENT_ID": "",
                    "GOOGLE_OAUTH_CLIENT_SECRET": "",
                },
                {
                    "GOOGLE_OAUTH_CLIENT_ID": "",
                },
            ]
        )

        self.assertEqual(merged["GOOGLE_OAUTH_CLIENT_ID"], "packaged-client")
        self.assertEqual(merged["GOOGLE_OAUTH_CLIENT_SECRET"], "packaged-secret")

    def test_saved_runtime_value_replaces_packaged_value(self) -> None:
        merged = _merge_env_values(
            [
                {"GOOGLE_OAUTH_CLIENT_ID": "packaged-client"},
                {"GOOGLE_OAUTH_CLIENT_ID": "saved-client"},
            ]
        )

        self.assertEqual(merged["GOOGLE_OAUTH_CLIENT_ID"], "saved-client")
