"""
Data access for the global navbar search bar (ADR-44).

One JSON endpoint (`routes/search.py`) searches four entity types at once -
Students, Payments, Enquiries, Cashbook - in a single grouped response. Each
function below does the same "fetch this admin's own rows, filter in
Python" as every other cross-table read in this codebase (PostgREST has no
server-side ilike/JOIN in the client used here), scoped to admin_id exactly
the way every other admin-scoped query in this app is (ADR-2) - a query that
forgets that scoping would leak another library owner's data.

Students/Payments/Cashbook reuse existing admin-scoped fetchers
(`get_admin_students`, `get_payments_for_admin`, `get_cashbook_ledger`'s own
`search=` param) rather than re-deriving them. Enquiries has no reusable
query function today (routes/enquiries.py's index() inlines its own read),
so search_enquiries() below is a small, direct admin-scoped read, same shape.
"""

from postgrest.exceptions import APIError

from database.cashbook_queries import get_cashbook_ledger
from database.membership_queries import get_admin_students
from database.payment_queries import get_payments_for_admin
from database.supabase_client import get_supabase_client

# Per-type cap for the grouped dropdown - keeps every one of the four
# groups short enough to scan without scrolling past it to reach the next
# one, regardless of how many rows truly match in a large library.
RESULTS_PER_TYPE = 5


def search_students(admin_id, query, limit=RESULTS_PER_TYPE):
    """Students whose name or mobile contains `query` (case-insensitive,
    partial). Reuses get_admin_students() - the same admin-scoped fetch
    database.ai_center_queries.search_students() uses - but returns bare
    matches with no plan_name enrichment: the navbar dropdown doesn't need
    it, and skipping it avoids a second get_memberships_for_admin() round
    trip on every keystroke.
    """

    students = get_admin_students(admin_id)
    needle = query.lower()
    matches = [
        s for s in students
        if needle in (s.get("full_name") or "").lower()
        or needle in (s.get("mobile") or "")
    ]
    return matches[:limit]


def search_payments(admin_id, query, limit=RESULTS_PER_TYPE):
    """Payments whose receipt number, student name, or remarks contain
    `query`. Reuses get_payments_for_admin() (students-first-then-in_,
    full_name already enriched in Python)."""

    payments = get_payments_for_admin(admin_id)
    needle = query.lower()
    matches = [
        p for p in payments
        if needle in (p.get("receipt_number") or "").lower()
        or needle in (p.get("full_name") or "").lower()
        or needle in (p.get("remarks") or "").lower()
    ]
    return matches[:limit]


def search_enquiries(admin_id, query, limit=RESULTS_PER_TYPE):
    """Enquiries whose name, mobile, purpose, shift, or remarks contain
    `query` - a direct .eq("admin_id", ...) read (same scoping shape as
    routes/enquiries.py's own index(), which has no reusable function to
    call here), filtered in Python."""

    supabase = get_supabase_client()
    try:
        response = (
            supabase.table("enquiries")
            .select("enquiry_id, full_name, mobile, purpose, preferred_shift, remarks")
            .eq("admin_id", admin_id)
            .execute()
        )
        enquiries = response.data
    except APIError:
        enquiries = []

    needle = query.lower()
    matches = [
        e for e in enquiries
        if needle in (e.get("full_name") or "").lower()
        or needle in (e.get("mobile") or "")
        or needle in (e.get("purpose") or "").lower()
        or needle in (e.get("preferred_shift") or "").lower()
        or needle in (e.get("remarks") or "").lower()
    ]
    return matches[:limit]


def search_cashbook(admin_id, query, limit=RESULTS_PER_TYPE):
    """Cashbook entries whose category/person/description/reference_id
    contain `query`. A thin wrapper around get_cashbook_ledger()'s own
    `search=` param and pagination cap - no new filtering logic needed
    here at all."""

    return get_cashbook_ledger(admin_id, search=query, per_page=limit)["rows"]


def global_search(admin_id, query, limit_per_type=RESULTS_PER_TYPE):
    """Runs all four searches above and returns them grouped by type, for
    the navbar's autocomplete dropdown. A blank/whitespace-only query
    short-circuits to four empty lists - the same empty-query guard
    database.ai_center_queries.search_students() uses - rather than
    fetching every admin-scoped table for nothing."""

    query = (query or "").strip()
    if not query:
        return {"students": [], "payments": [], "enquiries": [], "cashbook": []}

    return {
        "students": search_students(admin_id, query, limit_per_type),
        "payments": search_payments(admin_id, query, limit_per_type),
        "enquiries": search_enquiries(admin_id, query, limit_per_type),
        "cashbook": search_cashbook(admin_id, query, limit_per_type),
    }
