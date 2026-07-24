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
