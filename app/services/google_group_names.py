from __future__ import annotations

import re


_GOOGLE_SHARED_SUFFIX = re.compile(r"\s*\(\s*shared\s*\)\s*$", re.IGNORECASE)
RETIRED_CATCHALL_GROUP_NAME = "TriState Separates"


def strip_google_shared_suffix(value: str | None) -> str:
    """Remove a trailing Google Contacts `` (Shared)`` suffix only.

    Leaves the word Shared in the middle of a real Field/Meeting title unchanged.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    return _GOOGLE_SHARED_SUFFIX.sub("", text).strip()


def has_google_shared_suffix(value: str | None) -> bool:
    """True when the Google label title itself ends in `` (Shared)``."""
    text = str(value or "").strip()
    return bool(text) and strip_google_shared_suffix(text) != text


def is_retired_catchall_group_name(value: str | None) -> bool:
    """True for the retired all-contacts Google group, with or without `` (Shared)``."""
    return strip_google_shared_suffix(value).casefold() == RETIRED_CATCHALL_GROUP_NAME.casefold()


def usable_shared_contacts_group_name(value: str | None) -> str:
    """Return a configured catch-all name, or empty when none should be appended."""
    cleaned = strip_google_shared_suffix(value)
    if not cleaned or is_retired_catchall_group_name(cleaned):
        return ""
    return cleaned


def google_group_names_equivalent(left: str | None, right: str | None) -> bool:
    left_key = strip_google_shared_suffix(left).casefold()
    right_key = strip_google_shared_suffix(right).casefold()
    return bool(left_key and right_key and left_key == right_key)


def parse_field_meeting_from_group_names(group_names: list[str] | None) -> tuple[str, str]:
    from app.services.region_group_names import is_region_group_name

    for name in group_names or []:
        text = strip_google_shared_suffix(name)
        if " - " not in text or is_region_group_name(text):
            continue
        field_name, meeting_name = text.split(" - ", 1)
        field_name = strip_google_shared_suffix(field_name.strip())
        meeting_name = strip_google_shared_suffix(meeting_name.strip())
        if field_name and meeting_name and not is_region_group_name(field_name):
            return field_name, meeting_name
    return "", ""


def normalize_google_group_names(names: list[str] | None) -> list[str]:
    """Strip `` (Shared)`` from each name and drop equivalent duplicates.

    Prefers the already-clean spelling when both ``Foo`` and ``Foo (Shared)`` appear.
    Drops the retired TriState Separates catch-all group entirely.
    """
    result: list[str] = []
    seen: set[str] = set()
    for name in names or []:
        cleaned = strip_google_shared_suffix(name)
        key = cleaned.casefold()
        if not cleaned or key in seen or is_retired_catchall_group_name(cleaned):
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def strip_google_shared_suffix_from_joined(value: str | None, *, joiner: str = "\n") -> str:
    text = str(value or "").replace("\r", "\n")
    parts: list[str] = []
    seen: set[str] = set()
    for chunk in text.replace(";", "\n").split("\n"):
        cleaned = strip_google_shared_suffix(chunk)
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        parts.append(cleaned)
    return joiner.join(parts)


def normalize_group_membership_text(value: str | None) -> str:
    text = str(value or "").replace(":::", "\n").replace(";", "\n")
    names: list[str] = []
    for chunk in text.splitlines():
        if chunk.strip().lower() == "no entry":
            continue
        names.append(chunk)
    return ":::".join(normalize_google_group_names(names))
