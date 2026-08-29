"""Assign the next integer id for a table whose Postgres identity sequence
can't be trusted to stay ahead of explicit inserts.

`enquiries.enquiry_id` / `students.student_id` (and others) have an identity
sequence that was seeded once from a one-time data copy (ADR-15) and now
trails ordinary usage, so `routes/enquiries.py`'s `add()` and
`routes/student.py`'s `admission()` assign the id themselves as
``MAX(id) + 1``. That read-then-insert races under a double-submit: two
requests read the same `MAX` and both try to insert it; the loser hits a
primary-key collision (Postgres ``23505``) that used to surface to the user
as a bare "Something went wrong. Please try again." (see TD-78).

`insert_with_next_id()` retries the `MAX+1` / insert a few times on that
specific collision, so a genuine concurrent insert just gets the next id
instead of an error. Any other failure is re-raised unchanged.
"""

from postgrest.exceptions import APIError

from database.supabase_client import get_supabase_client

_MAX_RETRIES = 6


def _is_unique_violation(error):
    """True for a Postgres UNIQUE / primary-key violation (code 23505) -
    same detection shape as `database/membership_queries.py`'s
    `_is_unique_violation()`."""
    details = error.args[0] if error.args else ""
    code = details.get("code") if isinstance(details, dict) else str(details)
    return "23505" in (code or "")


def insert_with_next_id(table, id_column, row):
    """Insert ``row`` into ``table`` with ``row[id_column]`` set to
    ``MAX(id) + 1``, retrying on a primary-key collision from a concurrent
    identical insert. Returns the assigned id. Re-raises `APIError` for any
    other failure, or the last collision if every retry lost the race."""
    supabase = get_supabase_client()
    last_error = None

    for _ in range(_MAX_RETRIES):
        top = (
            supabase.table(table)
            .select(id_column)
            .order(id_column, desc=True)
            .limit(1)
            .execute()
        )
        next_id = (top.data[0][id_column] + 1) if top.data else 1

        try:
            supabase.table(table).insert({**row, id_column: next_id}).execute()
            return next_id
        except APIError as error:
            if not _is_unique_violation(error):
                raise
            last_error = error

    raise last_error
