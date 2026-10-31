from __future__ import annotations

import re

from app.services.google_group_names import (
    strip_google_shared_suffix,
    usable_shared_contacts_group_name,
)


REGION_GROUP_NCCFS = "NCcfs"
REGION_GROUP_VACFS = "VAcfs"
REGION_GROUP_NO_FIELD = "no field"
REGION_GROUP_NAMES = (REGION_GROUP_NCCFS, REGION_GROUP_VACFS, REGION_GROUP_NO_FIELD)
YEAR_FIELD_PATTERN = re.compile(r"^[0-9]{4}$")

NCCFS_FIELDS = frozenset(
    {
        "NC Eastern Field/Raleigh",
        "South Carolina",
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
        return REGION_GROUP_NO_FIELD
    if field_name in NCCFS_FIELDS or YEAR_FIELD_PATTERN.fullmatch(field_name):
        return REGION_GROUP_NCCFS
    if field_name in VACFS_FIELDS:
        return REGION_GROUP_VACFS
    return REGION_GROUP_NO_FIELD


def is_region_group_name(value: str | None) -> bool:
    cleaned = strip_google_shared_suffix(value)
    return cleaned in REGION_GROUP_NAMES


def region_group_preview_payload() -> dict:
    """JSON-serializable Field → region map for Edit/Move previews."""
    return {
        "nccfs_fields": sorted(NCCFS_FIELDS),
        "vacfs_fields": sorted(VACFS_FIELDS),
        "nccfs_label": REGION_GROUP_NCCFS,
        "vacfs_label": REGION_GROUP_VACFS,
        "no_field": REGION_GROUP_NO_FIELD,
        "year_pattern": YEAR_FIELD_PATTERN.pattern,
    }


def contact_group_membership_names(
    field_value: str | None,
    meeting_value: str | None,
    *,
    shared_group_name: str | None = None,
) -> list[str]:
    """Canonical groups: optional Field-Meeting, one region, optional catch-all, myContacts."""
    field_name = strip_google_shared_suffix(str(field_value or "").strip())
    meeting_name = strip_google_shared_suffix(str(meeting_value or "").strip())
    names: list[str] = []
    if field_name and meeting_name:
        names.append(f"{field_name} - {meeting_name}")
    names.append(region_group_name_for_field(field_name))
    if shared_group_name is None:
        from app.services.preset_service import get_shared_contacts_group_name

        catch_all = usable_shared_contacts_group_name(get_shared_contacts_group_name())
    else:
        catch_all = usable_shared_contacts_group_name(shared_group_name)
    if catch_all:
        names.append(catch_all)
    names.append("myContacts")
    return names
