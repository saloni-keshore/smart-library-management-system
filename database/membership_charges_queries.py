"""
Reusable data access for a membership's extra charges (ADR-66).

An "extra charge" is a one-time or monthly amount added on top of the plan /
shift-slot fee - registration, a refundable security deposit, a monthly seat
reservation, a monthly locker. The catalog of charge *keys* and their
built-in behaviour (recurring? refundable? which Cashbook category?) lives
here in `CHARGE_CATALOG`; the admin configures only the amount and a
Compulsory/Optional flag per key, in Settings > Membership Settings.

"registration" is special: it reuses `membership_settings.admission_fee` and
the existing `memberships.admission_fee_amount` snapshot / "Admission Fee"
Cashbook category (ADR-62), so it is never written to `membership_charges` -
it stays in `get_charge_config()` only so the Settings form and the
Create/Renew "compulsory vs optional" logic can treat all four uniformly.

`membership_charges` is a brand-new table (ADR-14/38/40 - no DDL path). Reads
degrade to `[]` when it doesn't exist yet; `insert_membership_charges()`
raises `ChargeTableUnavailable` (caught by routes/membership.py, which then
deletes the just-inserted membership row so nothing is half-saved) only when
a charge with a real non-zero amount would otherwise be silently lost.
"""

from postgrest.exceptions import APIError

from database.membership_queries import _is_undefined_column_error
from database.supabase_client import get_supabase_client


# Ordered: this is also the Cashbook admission-fee-first waterfall order
# (registration -> deposit -> seat -> locker -> membership fee).
CHARGE_CATALOG = [
    {
        "key": "registration",
        "label": "Registration Fee",
        "recurring": False,
        "refundable": False,
        "cashbook": "Admission Fee",
        "fee_key": "admission_fee",
        "compulsory_key": "registration_compulsory",
        "compulsory_default": 1,
        "in_charges_table": False,   # stays on memberships.admission_fee_amount
    },
    {
        "key": "security_deposit",
        "label": "Security Deposit",
        "recurring": False,
        "refundable": True,
        "cashbook": "Security Deposit",
        "fee_key": "security_deposit_amount",
        "compulsory_key": "security_deposit_compulsory",
        "compulsory_default": 1,
        "in_charges_table": True,
    },
    {
        "key": "seat_reservation",
        "label": "Seat Reservation",
        "recurring": True,
        "refundable": False,
        "cashbook": "Seat Reservation",
        "fee_key": "seat_reservation_fee",
        "compulsory_key": "seat_reservation_compulsory",
        "compulsory_default": 0,
        "in_charges_table": True,
    },
    {
        "key": "locker",
        "label": "Locker",
        "recurring": True,
        "refundable": False,
        "cashbook": "Locker",
        "fee_key": "locker_fee",
        "compulsory_key": "locker_compulsory",
        "compulsory_default": 0,
        "in_charges_table": True,
    },
]

CHARGE_BY_KEY = {c["key"]: c for c in CHARGE_CATALOG}


class ChargeTableUnavailable(Exception):
    """Raised when a membership is being sold with a real, non-zero extra
    charge but `membership_charges` doesn't exist yet on this Supabase
    project (ADR-66's CREATE TABLE hasn't been run). The caller must not
    keep the membership - its total_fee already includes the charge, so
    persisting it without the charge rows would collect money the Cashbook
    can never categorize or (for the deposit) refund."""


def get_charge_config(settings):
    """The four charges as an ordered list of dicts:
    {key, label, amount, compulsory, recurring, refundable, cashbook}.
    `settings` is a membership_settings row or None; a missing/None amount
    or flag falls back to 0 / the catalog default, so nothing is ever
    charged until an admin sets an amount."""

    settings = settings or {}
    config = []
    for c in CHARGE_CATALOG:
        amount = settings.get(c["fee_key"])
        compulsory = settings.get(c["compulsory_key"])
        config.append({
            "key": c["key"],
            "label": c["label"],
            "amount": float(amount or 0),
            "compulsory": bool(c["compulsory_default"] if compulsory is None else compulsory),
            "recurring": c["recurring"],
            "refundable": c["refundable"],
            "cashbook": c["cashbook"],
        })
    return config


def get_membership_charges(membership_id):
    """Every extra-charge row for a membership (seat/locker/deposit), or
    `[]` - including when `membership_charges` doesn't exist yet."""

    supabase = get_supabase_client()
    try:
        response = (
            supabase.table("membership_charges")
            .select("*")
            .eq("membership_id", membership_id)
            .execute()
        )
    except APIError:
        return []
    return response.data or []


def insert_membership_charges(supabase, membership_id, charges):
    """Bulk-insert charge rows for a membership. `charges` is a list of
    dicts {charge_key, label, amount, recurring, refundable}. A no-op for an
    empty list. Raises ChargeTableUnavailable if the table is missing and
    any charge has a non-zero amount; silently no-ops if the table is
    missing but every amount is 0."""

    rows = [
        {
            "membership_id": membership_id,
            "charge_key": c["charge_key"],
            "label": c["label"],
            "amount": c["amount"],
            "recurring": 1 if c["recurring"] else 0,
            "refundable": 1 if c["refundable"] else 0,
        }
        for c in charges
    ]
    if not rows:
        return

    try:
        supabase.table("membership_charges").insert(rows).execute()
    except APIError as error:
        if not _is_undefined_column_error(error) and not _is_missing_table_error(error):
            raise
        if any(row["amount"] for row in rows):
            raise ChargeTableUnavailable() from error
        # every amount is 0 - nothing worth persisting, degrade quietly


def mark_charge_refunded(supabase, membership_id, charge_key, on_date):
    """Stamp refunded_on for one charge row (idempotency is the caller's
    job - it checks the row isn't already refunded first)."""

    supabase.table("membership_charges").update(
        {"refunded_on": on_date}
    ).eq("membership_id", membership_id).eq("charge_key", charge_key).execute()


def _is_missing_table_error(error):
    """True for PostgREST's "Could not find the table" (PGRST205) - a
    brand-new table not yet created on this project, same detection shape
    as database/panda_queries.py."""

    details = error.args[0] if error.args else ""
    code = details.get("code") if isinstance(details, dict) else str(details)
    return "PGRST205" in (code or "")
