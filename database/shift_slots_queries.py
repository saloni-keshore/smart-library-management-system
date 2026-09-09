"""
Reusable, admin-isolated data access for Settings > Shift Slots (ADR-65).

A shift slot is one time-window membership option a library sells - a name,
an optional start/end time, an hours label, and a monthly fee (or a
per-hour rate for a night-hourly slot). One admin owns many slots.

`shift_slots` is a brand-new table, not applicable by this app itself - see
its CREATE TABLE comment in database/supabase_migration.sql (this app has no
DDL path, ADR-14/38/40). Every read here degrades to `[]` / `None` if the
table doesn't exist yet (PostgREST raises `PGRST205`, caught the same as any
other read failure), so the Create/Renew shift dropdown is simply hidden and
the fixed duration plans keep working. Writes let `APIError` propagate for
routes/setting.py to turn into a clear flash message.
"""

import httpx
from postgrest.exceptions import APIError

from database.id_sequence import insert_with_next_id
from database.membership_queries import resolve_slot_bucket, _minutes_since_midnight
from database.settings_queries import _now_iso
from database.supabase_client import get_supabase_client


# Fields a Settings form controls; everything else on the row is
# server-managed (slot_id, admin_id, timestamps).
_SLOT_FIELDS = (
    "name", "start_time", "end_time", "hours_label", "monthly_fee",
    "time_bucket", "is_night_hourly", "night_hourly_rate", "active",
    "sort_order",
)

HOURS_LABELS = ["Full Day", "7", "4", "Night-hourly", "Custom"]


def _clean_payload(data):
    """Keep only known slot columns; normalise the empty string to NULL for
    the nullable time columns and the optional bucket override."""

    payload = {k: data[k] for k in _SLOT_FIELDS if k in data}
    for nullable in ("start_time", "end_time", "time_bucket"):
        if nullable in payload and not (payload[nullable] or "").strip():
            payload[nullable] = None
    return payload


def _slot_span_hours(slot):
    """Whole-ish hours a slot actually runs (end - start, wrapping past
    midnight), or None when it has no fixed window. start == end is read as
    a 24h slot, not a 0h one."""

    lo = _minutes_since_midnight(slot.get("start_time"))
    hi = _minutes_since_midnight(slot.get("end_time"))
    if lo is None or hi is None:
        return None
    span = (hi - lo) % (24 * 60)
    return round(span / 60, 1) if span else 24


def get_shift_slots(admin_id, include_inactive=False):
    """This admin's shift slots, each annotated with `resolved_bucket`
    (Morning/Afternoon/Evening/Night/Full Day), sorted by sort_order then
    name. `[]` when the table doesn't exist yet or the admin has none."""

    supabase = get_supabase_client()

    try:
        query = (
            supabase.table("shift_slots")
            .select("*")
            .eq("admin_id", admin_id)
        )
        if not include_inactive:
            query = query.eq("active", 1)
        response = query.execute()
    except (APIError, httpx.TransportError):
        return []

    slots = response.data or []
    for slot in slots:
        slot["resolved_bucket"] = resolve_slot_bucket(slot)
        slot["span_hours"] = _slot_span_hours(slot)
    slots.sort(key=lambda s: (s.get("sort_order") or 0, (s.get("name") or "").lower()))
    return slots


def get_shift_slot(admin_id, slot_id):
    """One admin-scoped slot row (with `resolved_bucket`), or None."""

    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("shift_slots")
            .select("*")
            .eq("admin_id", admin_id)
            .eq("slot_id", slot_id)
            .limit(1)
            .execute()
        )
    except APIError:
        return None

    if not response.data:
        return None
    slot = response.data[0]
    slot["resolved_bucket"] = resolve_slot_bucket(slot)
    slot["span_hours"] = _slot_span_hours(slot)
    return slot


def create_shift_slot(admin_id, data):
    """Insert a new slot. Raises APIError if `shift_slots` doesn't exist yet
    on this project (routes/setting.py catches it)."""

    payload = _clean_payload(data)
    payload["admin_id"] = admin_id
    return insert_with_next_id("shift_slots", "slot_id", payload)


def update_shift_slot(admin_id, slot_id, data):
    """Update an existing admin-scoped slot."""

    supabase = get_supabase_client()
    payload = _clean_payload(data)
    payload["updated_at"] = _now_iso()
    supabase.table("shift_slots").update(payload).eq("admin_id", admin_id).eq(
        "slot_id", slot_id
    ).execute()


def set_shift_slot_active(admin_id, slot_id, active):
    """Soft-enable/disable a slot (slots are never deleted - a membership
    may still reference one by its snapshot)."""

    supabase = get_supabase_client()
    supabase.table("shift_slots").update(
        {"active": 1 if active else 0, "updated_at": _now_iso()}
    ).eq("admin_id", admin_id).eq("slot_id", slot_id).execute()
