from app.config import PROJECT_ROOT


DEFAULT_APP_VERSION = "1.0"
APP_VERSION_PATH = PROJECT_ROOT / "APP_VERSION"
APP_EDITION_PATH = PROJECT_ROOT / "APP_EDITION"
SINGLE_EDITOR_EDITION = "single-editor"
MULTI_EDITOR_EDITION = "multi-editor"
# This workspace is Single Editor NC. Its packages are published only to the NC
# page so they do not replace the shared Single Editor feed.
SINGLE_EDITOR_NC_UPDATE_FEED = "contactsfreeshare-se-nc-updates"
SHARED_SINGLE_EDITOR_UPDATE_FEED = "contactsfreeshare-se-updates"
MULTI_EDITOR_UPDATE_FEED = "contactsfreeshare-updates"
SINGLE_EDITOR_UPDATE_MANIFEST_URL = (
    f"https://menfisher.github.io/{SINGLE_EDITOR_NC_UPDATE_FEED}/app_update_manifest.json"
)
MULTI_EDITOR_UPDATE_MANIFEST_URL = (
    f"https://menfisher.github.io/{MULTI_EDITOR_UPDATE_FEED}/app_update_manifest.json"
)


def get_current_app_version() -> str:
    try:
        version = APP_VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        version = ""
    return version or DEFAULT_APP_VERSION


def get_app_edition() -> str:
    try:
        edition = APP_EDITION_PATH.read_text(encoding="utf-8").strip().lower()
    except OSError:
        edition = ""
    if edition in {SINGLE_EDITOR_EDITION, MULTI_EDITOR_EDITION}:
        return edition
    try:
        from app import config as app_config

        if bool(getattr(app_config, "SINGLE_EDITOR_ONLY", False)):
            return SINGLE_EDITOR_EDITION
    except Exception:
        pass
    return MULTI_EDITOR_EDITION


def get_app_edition_label() -> str:
    return "Single Editor NC" if get_app_edition() == SINGLE_EDITOR_EDITION else "Multi-Editor"


def get_expected_update_manifest_url() -> str:
    if get_app_edition() == SINGLE_EDITOR_EDITION:
        return SINGLE_EDITOR_UPDATE_MANIFEST_URL
    return MULTI_EDITOR_UPDATE_MANIFEST_URL


def update_manifest_url_matches_edition(url: str, edition: str = "") -> bool:
    text = str(url or "").strip().lower()
    current = str(edition or get_app_edition()).strip().lower()
    if current == SINGLE_EDITOR_EDITION:
        return SINGLE_EDITOR_NC_UPDATE_FEED in text
    return (
        MULTI_EDITOR_UPDATE_FEED in text
        and SHARED_SINGLE_EDITOR_UPDATE_FEED not in text
        and SINGLE_EDITOR_NC_UPDATE_FEED not in text
    )
