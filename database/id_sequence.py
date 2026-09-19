"""Insert a row into a table whose id column is a real Postgres IDENTITY,
relying on the database's own `nextval()` default instead of computing the
id in application code.

Originally (TD-78) this computed `MAX(id) + 1` and inserted it explicitly,
because the identity sequence was seeded once from a one-time SQLite ->
Supabase data copy (ADR-15) and might trail real usage. As of ADR-75's
shared-database multi-tenant conversion, that `MAX(id)` read went through a
tenant-scoped, Row-Level-Security-filtered client (`get_supabase_client()`)
- so a brand-new tenant's own rows are always empty, making the computed
`next_id` deterministically `1` and guaranteed to collide with any other
tenant's existing global row `1` (TD-108). This was not merely a race under
concurrency (the original 6x collision-retry loop was a no-op against it,
since a retried read recomputed the exact same wrong value) - it failed on
literally the first insert from any new tenant.

Fixed (ADR-79): after a one-time sequence realignment
(`database/supabase_id_sequence_fix_migration.sql`), insert WITHOUT an
explicit id column and read the DB-assigned id back from the response.
postgrest-py's `.insert().execute()` defaults to
`returning=ReturnMethod.representation`, so the assigned id is already in
`response.data[0][id_column]` - no extra round trip. A Postgres identity
sequence's `nextval()` is atomic and global, and is NOT subject to RLS (RLS
gates table rows, not sequence objects) - so no retry-on-collision loop is
needed any more; a real `APIError` is simply re-raised to the caller.
"""

from database.supabase_client import get_supabase_client


def insert_with_next_id(table, id_column, row):
    """Insert ``row`` into ``table``, letting the identity column assign its
    own id, and return that assigned id. Re-raises `APIError` for any insert
    failure."""
    supabase = get_supabase_client()
    response = supabase.table(table).insert(row).execute()
    return response.data[0][id_column]
