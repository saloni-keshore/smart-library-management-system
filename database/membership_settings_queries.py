"""
Reusable, admin-isolated data access for Settings > Membership Settings.

One row per admin_id. Supabase's `membership_settings` table is the source
of truth (ADR-24) - see database/settings_queries.py's module docstring for
why no SQLite mirror is kept (no other table enforces a foreign key against
this one).
"""

from postgrest.exceptions import APIError

from database.settings_queries import _now_iso
from database.supabase_client import get_supabase_client


# Extra-charge columns (ADR-66) - dropped and retried once if the live
# database doesn't have them yet, same silent-degrade as
# database/settings_queries.py's seating-capacity columns (ADR-38).
_CHARGE_FIELDS = (
    "seat_reservation_fee", "locker_fee", "security_deposit_amount",
    "registration_compulsory", "seat_reservation_compulsory",
    "locker_compulsory", "security_deposit_compulsory",
)

_UNDEFINED_COLUMN_ERROR_CODES = {"42703", "PGRST204"}


def _is_undefined_column_error(error):
    details = error.args[0] if error.args else ""
    code = details.get("code") if isinstance(details, dict) else str(details)
    return any(marker in (code or "") for marker in _UNDEFINED_COLUMN_ERROR_CODES)


def get_membership_settings(admin_id):

    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("membership_settings")
            .select("*")
            .eq("admin_id", admin_id)
            .execute()
        )
    except APIError:
        return None

    return response.data[0] if response.data else None


def save_membership_settings(admin_id, data):
    """Insert/update this admin's plan pricing and renewal policy.

    reminder_days/send_reminders are intentionally omitted here - reminder
    ownership moved to Settings > Notification Settings
    (library_settings.reminder_*/notify_* columns). Omitting them from the
    upsert payload leaves any existing values on this table untouched
    instead of overwriting them with stale form data - the same contract
    the old SQLite `INSERT ... ON CONFLICT DO UPDATE`'s column list
    enforced, now expressed as Supabase's default "merge-duplicates" upsert
    behaviour (only columns present in the payload are updated on conflict).
    See docs/11_FUTURE_WORK.md.
    """

    supabase = get_supabase_client()

    payload = {
        "admin_id": admin_id,
        "monthly_fee": data["monthly_fee"],
        "monthly_days": data["monthly_days"],
        "quarterly_fee": data["quarterly_fee"],
        "quarterly_days": data["quarterly_days"],
        "half_yearly_fee": data["half_yearly_fee"],
        "half_yearly_days": data["half_yearly_days"],
        "yearly_fee": data["yearly_fee"],
        "yearly_days": data["yearly_days"],
        "admission_fee": data["admission_fee"],
        "late_fee_per_day": data["late_fee_per_day"],
        "renewal_grace_days": data["renewal_grace_days"],
        "auto_expiry": data["auto_expiry"],
        "allow_early_renewal": data["allow_early_renewal"],
        "updated_at": _now_iso(),
    }
    for field in _CHARGE_FIELDS:
        if field in data:
            payload[field] = data[field]

    try:
        supabase.table("membership_settings").upsert(
            payload, on_conflict="admin_id"
        ).execute()
    except APIError as error:
        if not _is_undefined_column_error(error):
            raise
        # ADR-66 charge columns not on this project yet - persist the rest
        # (ADR-38 precedent); get_charge_config() then keeps returning 0s.
        fallback = {k: v for k, v in payload.items() if k not in _CHARGE_FIELDS}
        supabase.table("membership_settings").upsert(
            fallback, on_conflict="admin_id"
        ).execute()
