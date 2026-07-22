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

from database.db import get_connection


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

    from datetime import date as _date

    if membership_status == "Active" and end_date and str(end_date) < _date.today().isoformat():
        return "Expired"
    return membership_status


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def get_active_membership(student_id):
    """This student's currently-active membership (effective status), or
    None. Used to stop a second membership being created for a student who
    already has one live - renewal is the only supported way to replace an
    active membership."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT *, {EFFECTIVE_STATUS_SQL} AS effective_status
        FROM memberships m
        WHERE m.student_id = ?
        ORDER BY m.membership_id DESC
        LIMIT 1
    """, (student_id,))

    row = cursor.fetchone()
    conn.close()

    if row is not None and row["effective_status"] == "Active":
        return row
    return None


# ---------------------------------------------------------------------------
# Counts (shared by Dashboard and Membership Distribution)
# ---------------------------------------------------------------------------

def get_membership_counts(admin_id):
    """Distinct students with a currently-active vs. expired membership.

    Same query Dashboard and Membership Distribution each ran separately
    (identical WHERE logic, just split across 1 vs 2 SELECTs) - now one
    source of truth for both.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(DISTINCT CASE
                WHEN m.membership_status = 'Active' AND m.end_date >= DATE('now')
                THEN m.student_id END) AS active_total,
            COUNT(DISTINCT CASE
                WHEN m.membership_status = 'Active' AND m.end_date < DATE('now')
                THEN m.student_id END) AS expired_total
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE s.admin_id = ?
    """, (admin_id,))

    row = cursor.fetchone()
    conn.close()

    return {"active": row["active_total"], "expired": row["expired_total"]}


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
