"""
Reusable, admin-isolated data access for AI Center Settings - the weights
and risk-level thresholds `database/ai_center_queries.py`'s retention-risk
scoring engine reads, instead of hardcoding them (ADR-40).

One row per admin_id, same isolation pattern as Membership/Security
Settings. `ai_center_settings` is a brand-new table, not yet applicable by
this app itself - see the CREATE TABLE's comment in
database/supabase_migration.sql and ADR-40 for why (this app has no DDL
path, ADR-14/ADR-38). Every read here degrades to None (→ DEFAULTS) if the
table doesn't exist yet or this admin has never saved a row - callers should
never treat "no row" as an error condition.
"""

from postgrest.exceptions import APIError

from database.settings_queries import _now_iso
from database.supabase_client import get_supabase_client


DEFAULTS = {
    "weight_payment_delay": 45,
    "weight_renewal_history": 35,
    "weight_membership_duration": 20,
    "high_risk_max": 40,
    "low_risk_min": 70,
}


def get_ai_center_settings(admin_id):
    """This admin's saved weights/thresholds row, or None - either because
    it's never been saved, or because `ai_center_settings` doesn't exist yet
    on this Supabase project (verified live: PostgREST raises `PGRST205`
    for a missing table, caught here the same as any other read failure)."""

    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("ai_center_settings")
            .select("*")
            .eq("admin_id", admin_id)
            .execute()
        )
    except APIError:
        return None

    return response.data[0] if response.data else None


def get_effective_settings(admin_id):
    """DEFAULTS overlaid with whatever this admin has actually saved - the
    single dict every scoring/settings-page consumer should read, so none
    of them need to know whether a row exists yet or reimplement the
    fallback themselves."""

    saved = get_ai_center_settings(admin_id) or {}
    return {
        key: saved[key] if saved.get(key) is not None else default
        for key, default in DEFAULTS.items()
    }


def save_ai_center_settings(admin_id, data):
    """Upsert this admin's weights/thresholds. Validation (weights sum to
    100, high_risk_max < low_risk_min) is the caller's responsibility
    (routes/ai_center.py's settings()) - this function only persists
    whatever it's given. Raises postgrest.exceptions.APIError if
    `ai_center_settings` doesn't exist yet on this Supabase project; the
    caller catches this to flash a clear message instead of a 500."""

    supabase = get_supabase_client()

    supabase.table("ai_center_settings").upsert({
        "admin_id": admin_id,
        "weight_payment_delay": data["weight_payment_delay"],
        "weight_renewal_history": data["weight_renewal_history"],
        "weight_membership_duration": data["weight_membership_duration"],
        "high_risk_max": data["high_risk_max"],
        "low_risk_min": data["low_risk_min"],
        "updated_at": _now_iso(),
    }, on_conflict="admin_id").execute()
