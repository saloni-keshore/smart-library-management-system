"""
Reusable, admin-isolated data access for the Membership workflow.

`membership_status` on the `memberships` row is only flipped to 'Expired'
by the Renewal route (when a new membership replaces it) - it never
auto-flips just because `end_date` has passed. Every screen that needs to
know whether a membership is *actually* still active has to combine
`membership_status` with today's date itself. Before this module existed
that combination was written out independently in routes/student.py,
routes/dashboard.py, routes/membership.py and routes/membership_distribution.py
- four copies that could silently drift apart (see TD-6 in
docs/11_FUTURE_WORK.md). Everything here is that one definition, reused.
"""

from datetime import date as _date

from postgrest.exceptions import APIError

from database.supabase_client import get_supabase_client


# ---------------------------------------------------------------------------
# Effective status - the single definition of "is this membership active
# right now", in both SQL and Python form.
# ---------------------------------------------------------------------------

# Embed this in any query that SELECTs from `memberships m` and needs the
# real, date-aware status instead of the raw (possibly stale) column.
EFFECTIVE_STATUS_SQL = """
    CASE
        WHEN m.membership_status = 'Active' AND m.end_date < DATE('now')
        THEN 'Expired'
        ELSE m.membership_status
    END
"""

# Same "days until end_date" expression every membership/notification query
# needs (negative once expired).
DAYS_LEFT_SQL = "CAST(julianday(m.end_date) - julianday(DATE('now')) AS INTEGER)"


def get_effective_status(membership_status, end_date):
    """Python-side equivalent of EFFECTIVE_STATUS_SQL, for rows already
    fetched (e.g. a single membership dict) instead of re-querying."""

    if membership_status == "Active" and end_date and str(end_date) < _date.today().isoformat():
        return "Expired"
    return membership_status


def get_days_left(end_date):
    """Python-side equivalent of DAYS_LEFT_SQL, for rows already fetched
    from Supabase instead of a SQL expression evaluated in SQLite."""

    if not end_date:
        return None
    return (_date.fromisoformat(str(end_date)) - _date.today()).days


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def get_active_membership(student_id):
    """This student's currently-active membership (effective status), or
    None. Used to stop a second membership being created for a student who
    already has one live - renewal is the only supported way to replace an
    active membership.

    As of ADR-20, `routes/membership.py` is migrated to Supabase (the
    source of truth for `memberships`) and is this function's only caller,
    so it reads Supabase directly instead of the SQLite mirror the rest of
    this module still reads for the other, unmigrated modules below.
    """

    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("memberships")
            .select("*")
            .eq("student_id", student_id)
            .order("membership_id", desc=True)
            .limit(1)
            .execute()
        )
        row = response.data[0] if response.data else None
    except APIError:
        row = None

    if row is not None and get_effective_status(row["membership_status"], row["end_date"]) == "Active":
        return row
    return None


def promote_student_if_fully_paid(supabase, student_id):
    """Flip a provisional ('Pending') student to 'Active' once they have at
    least one membership and no outstanding balance across their
    memberships. One-directional: only ever 'Pending' -> 'Active', never a
    demotion, and never touches a student an operator has explicitly set
    'Active' or 'Inactive' (Student > Edit).

    Called at the end of the admission money steps -
    routes/membership.py's create() and routes/payment.py's collect() -
    so a student isn't fully admitted until membership + payment are
    actually complete (the fee is fully paid). Best-effort: the money
    write it follows has already succeeded, so any failure here is
    swallowed rather than rolled back or surfaced - same principle as the
    enquiry-status sync writes in routes/student.py.
    """

    try:
        student_resp = (
            supabase.table("students")
            .select("student_id, status")
            .eq("student_id", student_id)
            .execute()
        )
        student = student_resp.data[0] if student_resp.data else None
        if student is None or student["status"] != "Pending":
            return

        memberships_resp = (
            supabase.table("memberships")
            .select("pending_amount")
            .eq("student_id", student_id)
            .execute()
        )
        memberships = memberships_resp.data or []
        if not memberships:
            return
        if any(float(m["pending_amount"] or 0) > 0 for m in memberships):
            return

        supabase.table("students").update(
            {"status": "Active"}
        ).eq("student_id", student_id).execute()
    except APIError:
        pass


# ---------------------------------------------------------------------------
# Cross-table reads (Supabase has no server-side JOIN in the client used
# here, so every module below that used to run `memberships m JOIN students
# s ON ... WHERE s.admin_id = ?` against SQLite now fetches this admin's
# students and memberships separately and merges them in Python - the same
# shape routes/student.py's index() already established for its own
# students+memberships merge, ADR-19).
# ---------------------------------------------------------------------------

# Columns every current consumer of get_memberships_for_admin() needs off
# the student side (Dashboard/Membership Distribution only need
# full_name/mobile; Notifications also needs shift/purpose/join_date) -
# selected together so one shared query serves all of them.
_STUDENT_JOIN_COLUMNS = "student_id, full_name, mobile, shift, purpose, join_date"


def get_admin_students(admin_id):
    """This admin's students (id + the columns analytics consumers join
    against - see _STUDENT_JOIN_COLUMNS), or []. Callers that need the full
    student row should query Supabase `students` directly instead."""

    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("students")
            .select(_STUDENT_JOIN_COLUMNS)
            .eq("admin_id", admin_id)
            .execute()
        )
        return response.data
    except APIError:
        return []


def get_memberships_for_admin(admin_id):
    """Every membership belonging to this admin's students, each row
    enriched with that student's full_name/mobile/shift/purpose/join_date -
    the Python-side equivalent of `memberships m JOIN students s ON
    m.student_id = s.student_id WHERE s.admin_id = ?`. Used by Dashboard,
    Membership Distribution, Notifications and Business Intelligence, which
    all read this same join.
    """

    students = get_admin_students(admin_id)
    if not students:
        return []

    students_by_id = {s["student_id"]: s for s in students}

    supabase = get_supabase_client()
    try:
        response = (
            supabase.table("memberships")
            .select("*")
            .in_("student_id", list(students_by_id.keys()))
            .execute()
        )
        memberships = response.data
    except APIError:
        memberships = []

    for m in memberships:
        student = students_by_id.get(m["student_id"], {})
        m["full_name"] = student.get("full_name")
        m["mobile"] = student.get("mobile")
        m["shift"] = student.get("shift")
        m["purpose"] = student.get("purpose")
        m["join_date"] = student.get("join_date")

    return memberships


# ---------------------------------------------------------------------------
# Counts (shared by Dashboard and Membership Distribution)
# ---------------------------------------------------------------------------

def get_membership_counts(admin_id):
    """Distinct students with a currently-active vs. expired membership.

    Same query Dashboard and Membership Distribution each ran separately
    (identical WHERE logic, just split across 1 vs 2 SELECTs) - now one
    source of truth for both. Reads Supabase `students`/`memberships`
    (ADR-23) instead of the SQLite mirror.
    """

    memberships = get_memberships_for_admin(admin_id)
    today = _date.today().isoformat()

    active_students = set()
    expired_students = set()

    for m in memberships:
        if m["membership_status"] != "Active":
            continue
        if m["end_date"] and m["end_date"] >= today:
            active_students.add(m["student_id"])
        elif m["end_date"] and m["end_date"] < today:
            expired_students.add(m["student_id"])

    return {"active": len(active_students), "expired": len(expired_students)}


# ---------------------------------------------------------------------------
# Settings-driven plan pricing/duration (Membership Settings integration)
# ---------------------------------------------------------------------------

PLAN_SETTING_PREFIX = {
    "Monthly": "monthly",
    "Quarterly": "quarterly",
    "Half-Yearly": "half_yearly",
    "Yearly": "yearly",
}

# Used when this admin has never opened Settings > Membership Settings
# (get_membership_settings() returns None) - same defaults shown on that
# settings form itself.
DEFAULT_PLAN_DAYS = {"Monthly": 30, "Quarterly": 90, "Half-Yearly": 180, "Yearly": 365}
DEFAULT_PLAN_FEES = {"Monthly": 0, "Quarterly": 0, "Half-Yearly": 0, "Yearly": 0}
DEFAULT_ADMISSION_FEE = 0


def get_plan_pricing(settings):
    """Build {"Monthly": {"days": .., "fee": ..}, ...} from a
    membership_settings row (or None), for the Create/Renew forms to
    render plan duration/fee without hardcoding them in JS.
    """

    pricing = {}
    for plan, prefix in PLAN_SETTING_PREFIX.items():
        if settings is not None:
            pricing[plan] = {
                "days": settings[f"{prefix}_days"],
                "fee": settings[f"{prefix}_fee"],
            }
        else:
            pricing[plan] = {
                "days": DEFAULT_PLAN_DAYS[plan],
                "fee": DEFAULT_PLAN_FEES[plan],
            }

    return pricing


def get_admission_fee(settings):
    return settings["admission_fee"] if settings is not None else DEFAULT_ADMISSION_FEE


def split_admission_and_membership_fee(admission_fee_amount, old_paid, amount):
    """Admission-fee-first waterfall: split one payment of `amount` between
    Cashbook categories "Admission Fee" and "Membership Fee", given how much
    (`old_paid`) was already paid toward this membership before this
    payment.

    `admission_fee_amount` is this membership's own snapshot (see
    memberships.admission_fee_amount below), never the live Settings value -
    Settings can change after the membership was created. Every rupee paid
    toward a membership counts toward its admission fee first; only once
    that's fully covered does further money count as Membership Fee. This
    needs no separate running counter - "how much admission fee has been
    covered so far" is always exactly min(paid-so-far, admission_fee_amount),
    a pure function of the paid_amount progression memberships.py/payment.py
    already track (and already protect with idempotency), so there is no
    second total that could drift out of sync with it.

    Returns (admission_share, membership_share), summing to exactly `amount`.
    """

    admission_paid_before = min(old_paid, admission_fee_amount)
    admission_paid_after = min(old_paid + amount, admission_fee_amount)
    admission_share = admission_paid_after - admission_paid_before

    return admission_share, amount - admission_share


# ---------------------------------------------------------------------------
# Membership insert - tolerates discount_amount/discount_reason and
# admission_fee_amount not existing yet on a given Supabase project (ADR-46,
# ADR-62), without ADR-38's silent-strip fallback: both are financial/
# categorization data tied to a real, nonzero value entered or configured
# for this specific membership, so losing either silently would misrecord
# what was actually charged/categorized - a hard, visible failure is used
# instead. A membership with no discount and no configured admission fee
# (discount_amount/admission_fee_amount both 0, the common case for an admin
# who hasn't touched either feature) is unaffected either way.
# ---------------------------------------------------------------------------

_DISCOUNT_FIELDS = ("discount_amount", "discount_reason")
_ADMISSION_FEE_FIELDS = ("admission_fee_amount",)

_UNDEFINED_COLUMN_ERROR_CODES = {
    "42703",     # raw Postgres "column does not exist" (surfaced by .select())
    "PGRST204",  # PostgREST "column not found in schema cache" (surfaced by .insert()/.update())
}


def _is_undefined_column_error(error):
    """True when the live database is missing a column PostgREST otherwise
    validated the payload against - same detection database/settings_queries.py
    uses for library_settings' *_capacity columns (ADR-38). `APIError.args[0]`
    is a Python-repr string of the error dict, not an actual dict - matched
    with a plain substring check rather than parsed, so a genuinely
    unexpected error string doesn't get masked by a parse failure."""

    details = error.args[0] if error.args else ""
    if isinstance(details, dict):
        code = details.get("code")
    else:
        code = str(details)
    return any(marker in code for marker in _UNDEFINED_COLUMN_ERROR_CODES)


class DiscountColumnsUnavailable(Exception):
    """Raised when a membership row includes a real discount
    (discount_amount != 0 or discount_reason set) but the live database
    doesn't have discount_amount/discount_reason yet (ADR-46's ALTER TABLE
    hasn't been run on this Supabase project). The caller must not insert
    the membership in this case - total_fee already has the discount baked
    in, so inserting without these columns would charge the discounted
    price while silently losing the only record of why."""


class AdmissionFeeColumnUnavailable(Exception):
    """Raised when a membership row includes a real, nonzero
    admission_fee_amount (a standard plan with a configured Membership
    Settings admission fee) but the live database doesn't have that column
    yet (ADR-62's ALTER TABLE hasn't been run on this Supabase project). The
    caller must not insert the membership in this case - there would be
    nowhere to persist which portion of total_fee is the admission charge,
    and every later payment.collect() on it would then have no way to tell
    Admission Fee revenue apart from Membership Fee revenue for this
    membership, ever. A membership with no configured admission fee
    (admission_fee_amount == 0 - Custom plan, or Settings' admission fee is
    ₹0) is unaffected - see split_admission_and_membership_fee() above."""


def _is_unique_violation(error):
    """True for a Postgres UNIQUE-constraint violation (code 23505) - same
    detection shape as _is_undefined_column_error() above, just a different
    code. Used by insert_membership() to recognize "this exact
    idempotency_key was already inserted" instead of treating it as a
    generic database error (TD-30, ADR-53)."""

    details = error.args[0] if error.args else ""
    if isinstance(details, dict):
        code = details.get("code")
    else:
        code = str(details)
    return "23505" in (code or "")


def find_membership_by_idempotency_key(idempotency_key):
    """The membership row already inserted for this idempotency_key, or
    None. Used both by insert_membership() below (to detect a race that lost
    to a concurrent identical submission) and directly by
    routes/membership.py's create()/renew() (to short-circuit a slower
    duplicate - e.g. a back-button resubmit - before repeating any of the
    membership-status/payment side effects those routes perform). Returns
    None (never raises) if idempotency_key doesn't exist as a column yet on
    this Supabase project (ADR-53) - the same silent-degrade behavior
    insert_membership() itself falls back to."""

    if not idempotency_key:
        return None

    supabase = get_supabase_client()
    try:
        resp = (
            supabase.table("memberships")
            .select("*")
            .eq("idempotency_key", idempotency_key)
            .limit(1)
            .execute()
        )
    except APIError as error:
        if _is_undefined_column_error(error):
            return None
        raise
    return resp.data[0] if resp.data else None


def insert_membership(supabase, payload):
    """Insert a `memberships` row, tolerating discount_amount/discount_reason,
    admission_fee_amount, and idempotency_key not existing yet on this
    Supabase project.

    Discount columns and admission_fee_amount: only silently dropped when no
    real value was actually entered/configured for this membership (0 or
    absent - the common case for any admin not using the discount box, or
    with no admission fee configured, or on the Custom plan where
    admission_fee_amount is always 0 - see routes/membership.py's create()).
    If a real value is present and its column doesn't exist, raises
    DiscountColumnsUnavailable / AdmissionFeeColumnUnavailable instead of
    retrying without it - see those classes' docstrings. The two are
    independent (a project can be missing either without the other), so each
    gets its own retry tier rather than being lumped together.

    idempotency_key (TD-30, ADR-53): always silently dropped if the column
    doesn't exist yet - unlike discount/admission fee, this is an invisible
    safety net, not something the admin explicitly asked to record, so
    degrading to "no double-submit protection on this un-migrated project"
    is the right default rather than failing membership creation outright.

    Returns None on a normal insert. If payload carries an idempotency_key
    that was already used by an earlier, distinct request (a genuine
    double-submit that raced past this function's own pre-check in
    routes/membership.py), returns that earlier membership row instead of
    raising - the caller should treat this as "already done", not as an
    error.
    """

    idempotency_key = payload.get("idempotency_key")

    try:
        supabase.table("memberships").insert(payload).execute()
        return None
    except APIError as error:
        if _is_unique_violation(error) and idempotency_key:
            existing = find_membership_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
            raise
        if not _is_undefined_column_error(error):
            raise

    # Undefined-column error: idempotency_key is the more recently added,
    # always-optional column (ADR-53) - drop it first and retry, before
    # falling into the admission-fee/discount handling below, so a project
    # missing *only* idempotency_key isn't mistaken for one missing the
    # (differently-handled) financial columns.
    without_key = {k: v for k, v in payload.items() if k != "idempotency_key"}
    try:
        supabase.table("memberships").insert(without_key).execute()
        return None
    except APIError as error:
        if not _is_undefined_column_error(error):
            raise
        return _insert_membership_without_idempotency_key(
            supabase, payload, without_key, error
        )


def _insert_membership_without_idempotency_key(supabase, payload, without_key, error):
    """Tier 2/3 of insert_membership()'s retry cascade, reached once
    idempotency_key has already been dropped and the insert still fails
    with an undefined-column error. Split out from insert_membership()
    itself only so each `except APIError as error` block's `error` stays in
    scope for the `raise ... from error` it needs - Python unbinds an
    `except ... as name` variable as soon as that block ends."""

    # admission_fee_amount is checked next (ADR-62), independently of
    # discount below.
    if payload.get("admission_fee_amount"):
        raise AdmissionFeeColumnUnavailable() from error
    without_admission_fee = {
        k: v for k, v in without_key.items() if k not in _ADMISSION_FEE_FIELDS
    }
    try:
        supabase.table("memberships").insert(without_admission_fee).execute()
        return None
    except APIError as error:
        if not _is_undefined_column_error(error):
            raise
        if payload.get("discount_amount") or payload.get("discount_reason"):
            raise DiscountColumnsUnavailable() from error
        fallback = {
            k: v for k, v in without_admission_fee.items() if k not in _DISCOUNT_FIELDS
        }
        supabase.table("memberships").insert(fallback).execute()
        return None
