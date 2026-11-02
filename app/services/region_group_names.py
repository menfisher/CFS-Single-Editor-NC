from __future__ import annotations

import re

from app.services.google_group_names import (
    is_retired_catchall_group_name,
    strip_google_shared_suffix,
    usable_shared_contacts_group_name,
)


REGION_GROUP_NCCFS = "NCcfs"
REGION_GROUP_VACFS = "VAcfs"
REGION_GROUP_SCCFS = "SCcfs"
REGION_GROUP_NO_FIELD = "no field"
REGION_GROUP_NAMES = (
    REGION_GROUP_NCCFS,
    REGION_GROUP_VACFS,
    REGION_GROUP_SCCFS,
    REGION_GROUP_NO_FIELD,
)
YEAR_FIELD_PATTERN = re.compile(r"^[0-9]{4}$")
# NC as a CFS token: "NC Eastern", "NC/", "NC15". Does not match CONTACTS.
_NC_LABEL_SIGNAL = re.compile(r"(?i)(?:^|[\s/(])NC(?:[\s/]|15(?:\b)|$|-)")
# Pure South Carolina Field or a title that starts with that Field name.
_SOUTH_CAROLINA_TITLE = re.compile(r"(?i)^south carolina(?:\b|$)")
# "Virginia" in a Field/Meeting/Google label is enough (Southeast/Western/Northern
# Virginia). Also "(VA)" or a VA token after space/comma. Not NoVA/VACATION.
_VA_VIRGINIA_SIGNAL = re.compile(r"(?i)virginia")
_VA_PAREN_SIGNAL = re.compile(r"(?i)(?:^|\s)\(VA\)")
_VA_TOKEN_SIGNAL = re.compile(r"(?i)(?:^|[\s,/(])VA(?:[\s,)/]|$)")
_NC_FIELD_NAME_MARKERS = (
    "nc eastern",
    "nc central",
    "nc western",
    "nc15",
    "nc workers",
    "nc not printed",
    "nc northwest",
    "south sc",
    "fl ga sc workers",
)

NCCFS_FIELDS = frozenset(
    {
        "NC Eastern Field/Raleigh",
        "NC Central Field/Greensboro",
        "NC Western Field/Charlotte",
        "NC15 Not Printed",
        "NC Workers",
        "NC Central & South SC",
        "NC Northwest SC",
        "FL GA SC Workers",
        "NC Not Printed",
        "2026",
    }
)
SCCFS_FIELDS = frozenset({"South Carolina"})
VACFS_FIELDS = frozenset(
    {
        "Maryland and Delaware",
        "Southeast Virginia",
        "Western Virginia",
        "Northern Virginia and Fredericksburg",
        "Other Contacts",
    }
)


def region_group_name_for_field(field_value: str | None) -> str:
    """Return the single region token for a Field value."""
    field_name = strip_google_shared_suffix(str(field_value or "").strip())
    if not field_name:
        return REGION_GROUP_VACFS
    if field_name in SCCFS_FIELDS:
        return REGION_GROUP_SCCFS
    if field_name in NCCFS_FIELDS or YEAR_FIELD_PATTERN.fullmatch(field_name):
        return REGION_GROUP_NCCFS
    if field_name in VACFS_FIELDS:
        return REGION_GROUP_VACFS
    return REGION_GROUP_NO_FIELD


def is_region_group_name(value: str | None) -> bool:
    cleaned = strip_google_shared_suffix(value)
    return cleaned in REGION_GROUP_NAMES


def _usable_region_label_text(value: str | None) -> str:
    cleaned = strip_google_shared_suffix(value)
    if (
        not cleaned
        or is_retired_catchall_group_name(cleaned)
        or is_region_group_name(cleaned)
        or cleaned.casefold() == "mycontacts"
    ):
        return ""
    return cleaned


def _label_has_nc_field_name(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in _NC_FIELD_NAME_MARKERS)


def _label_has_va_field_name(text: str) -> bool:
    lowered = text.casefold()
    return bool(_VA_VIRGINIA_SIGNAL.search(text) or lowered.startswith("(va)") or " (va)" in lowered)


def _label_has_nc_signal(value: str | None) -> bool:
    text = _usable_region_label_text(value)
    if not text:
        return False
    if _label_has_nc_field_name(text):
        return True
    return bool(_NC_LABEL_SIGNAL.search(text))


def _label_has_va_signal(value: str | None) -> bool:
    text = _usable_region_label_text(value)
    if not text:
        return False
    if _label_has_va_field_name(text):
        return True
    return bool(_VA_PAREN_SIGNAL.search(text) or _VA_TOKEN_SIGNAL.search(text))


def _south_carolina_field_text(value: str | None) -> str:
    text = _usable_region_label_text(value)
    if not text:
        return ""
    if " - " in text:
        return text.split(" - ", 1)[0].strip()
    return text


def _label_has_sc_signal(value: str | None) -> bool:
    field_text = _south_carolina_field_text(value)
    return bool(field_text) and bool(_SOUTH_CAROLINA_TITLE.match(field_text))


def infer_region_from_label_texts(texts: list[str] | None) -> str:
    """Infer NCcfs/SCcfs/VAcfs from Field, Meeting, or existing group titles.

    NC in the label (NC Eastern, NC Central, NC Western, NC15, NC Workers,
    NC Not Printed, NC Central & South SC, NC Northwest SC) → NCcfs.
    NC wins over South Carolina in those mixed names.
    Pure South Carolina Field / title starting with ``South Carolina`` → SCcfs.
    ``FL GA SC Workers`` stays NCcfs.
    VA **or Virginia** → VAcfs (Southeast/Western/Northern Virginia).
    Prefers Field-Meeting labels over catch-alls. Ignores TriState Separates.
    Does not treat Shared in the middle of a real name as a signal.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in texts or []:
        text = _usable_region_label_text(raw)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    field_meeting = [text for text in cleaned if " - " in text]
    other = [text for text in cleaned if " - " not in text]
    for group in (field_meeting, other):
        nc = any(_label_has_nc_signal(text) for text in group)
        sc = any(_label_has_sc_signal(text) for text in group)
        va = any(_label_has_va_signal(text) for text in group)
        if nc:
            return REGION_GROUP_NCCFS
        if sc:
            return REGION_GROUP_SCCFS
        if va:
            return REGION_GROUP_VACFS
    return ""


def region_group_name_for_contact(
    field_value: str | None,
    meeting_value: str | None = None,
    extra_labels: list[str] | None = None,
    parsed_field: str | None = None,
) -> str:
    """Region token: hardcoded Field map first, then NC/SC/VA label text."""
    stored_field = strip_google_shared_suffix(str(field_value or "").strip())
    stored_meeting = strip_google_shared_suffix(str(meeting_value or "").strip())
    extras = list(extra_labels or [])
    mapped = region_group_name_for_field(stored_field)
    parsed = strip_google_shared_suffix(str(parsed_field or "").strip())
    if not stored_field and parsed:
        parsed_mapped = region_group_name_for_field(parsed)
        if parsed_mapped != REGION_GROUP_NO_FIELD:
            return parsed_mapped
    if mapped != REGION_GROUP_NO_FIELD:
        if stored_field:
            return mapped
        inferred = infer_region_from_label_texts([stored_meeting, *extras])
        return inferred or REGION_GROUP_VACFS
    inferred = infer_region_from_label_texts([stored_field, stored_meeting, *extras])
    return inferred or REGION_GROUP_NO_FIELD


def region_group_preview_payload() -> dict:
    """JSON-serializable Field → region map for Edit/Move previews."""
    return {
        "nccfs_fields": sorted(NCCFS_FIELDS),
        "sccfs_fields": sorted(SCCFS_FIELDS),
        "vacfs_fields": sorted(VACFS_FIELDS),
        "nccfs_label": REGION_GROUP_NCCFS,
        "sccfs_label": REGION_GROUP_SCCFS,
        "vacfs_label": REGION_GROUP_VACFS,
        "empty_field_label": REGION_GROUP_VACFS,
        "no_field": REGION_GROUP_NO_FIELD,
        "year_pattern": YEAR_FIELD_PATTERN.pattern,
    }


def contact_group_membership_names(
    field_value: str | None,
    meeting_value: str | None,
    *,
    shared_group_name: str | None = None,
    extra_labels: list[str] | None = None,
) -> list[str]:
    """Canonical groups: optional Field-Meeting, one region, optional catch-all, myContacts."""
    from app.services.google_group_names import parse_field_meeting_from_group_names

    stored_field = strip_google_shared_suffix(str(field_value or "").strip())
    stored_meeting = strip_google_shared_suffix(str(meeting_value or "").strip())
    extras = [strip_google_shared_suffix(str(item or "").strip()) for item in (extra_labels or [])]
    parsed_field, parsed_meeting = parse_field_meeting_from_group_names(extras)
    pair_field = stored_field or parsed_field
    pair_meeting = stored_meeting or parsed_meeting
    names: list[str] = []
    if pair_field and pair_meeting:
        names.append(f"{pair_field} - {pair_meeting}")
    names.append(
        region_group_name_for_contact(
            stored_field,
            stored_meeting,
            extra_labels=extras,
            parsed_field=parsed_field,
        )
    )
    if shared_group_name is None:
        from app.services.preset_service import get_shared_contacts_group_name

        catch_all = usable_shared_contacts_group_name(get_shared_contacts_group_name())
    else:
        catch_all = usable_shared_contacts_group_name(shared_group_name)
    if catch_all:
        names.append(catch_all)
    names.append("myContacts")
    return names
