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

    supabase.table("membership_settings").upsert({
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
    }, on_conflict="admin_id").execute()
