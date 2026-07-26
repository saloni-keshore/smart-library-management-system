"""
One-time migration: bring existing Supabase rows in line with the shared
input-normalization rules in utils/normalization.py.

Every row currently in the database was written before centralized
normalization existed, so `purpose`/`shift`/`plan_name`/`payment_mode` may
carry any mix of case ("upsc", "Upsc", "UPSC", ...), and person/location
fields may not be Title Case. That's exactly the "same category split into
several buckets by capitalization alone" problem the normalization pass
exists to prevent (see docs/DECISIONS.md) - existing rows need it applied
once, retroactively, or analytics/search/filtering would still be wrong for
every row written before this change.

`TABLE_RULES` started with `enquiries`/`students`/`memberships`/`payments`/
`library_settings` and was later extended with `admins.full_name`/`mobile`
and `cashbook.person`/`description` once a normalization audit found those
two write paths (`routes/auth.py`'s `register()`, `routes/cashbook.py`'s
`add_transaction()`/`edit_transaction()`) had been bypassing normalization -
this file's `TABLE_RULES` dict is the single place to check what's actually
covered; don't assume the module docstring alone is exhaustive.

Run once, by hand, from the project root:
    python -m database.migrate_normalize_input_data

Safe to re-run: normalizing an already-normalized value is a no-op, and a
row is only written back if its normalized value actually differs from
what's stored (so a second run reports 0 rows updated everywhere).

Paginates every table via `.range()` (see `_normalize_table()`) rather than
one unranged `.select("*").execute()` - PostgREST caps an unranged select at
its configured max-rows (1000 on this project), so the first two runs of
this script (before this fix) silently only ever scanned each table's first
1000 rows, undercounting every table with more rows than that.

Writes each changed row back with a targeted `.update(changes).eq(pk, ...)`
call (only the columns that actually differ), one request per changed row -
**not** a bulk `.upsert()`. A bulk-upsert version was tried and reverted:
Postgres validates every `NOT NULL` column against the upsert's *tentative
INSERT row* before `ON CONFLICT DO UPDATE` ever resolves, so any column not
included in a given upsert payload (e.g. `cashbook.type`/`amount`, not part
of this table's `field_rules`) fails a not-null constraint even though the
row already exists and only an UPDATE was ever intended - reproduced live
against `cashbook` (`null value in column "type" ... violates not-null
constraint`) before this was caught. A plain `.update()` has no such
restriction, since it never constructs a candidate INSERT row at all.
`enquiries`/`students`/`memberships`/`payments`/`library_settings`'s tables
run into the low thousands of rows and `admins` into five figures (inflated
by every pytest run creating fresh throwaway test rows) - at one
request-per-changed-row, that's a genuinely long-running script, so this
version also periodically re-creates the Supabase client (`_REFRESH_EVERY`
rows) and retries each request a few times with backoff (`_with_retry()`):
the very first full run of the original one-`update()`-per-row shape had
its HTTP/2 connection terminated by the remote (`httpx.RemoteProtocolError:
ConnectionTerminated`) partway through, after ~9,500 requests over the same
persistent connection.
"""

import time

from postgrest.exceptions import APIError

from database.supabase_client import get_supabase_client
from utils.normalization import (
    normalize_name,
    normalize_phone,
    normalize_category,
    normalize_location,
    normalize_free_text,
)

# table -> (primary key column, {column: normalizer function})
TABLE_RULES = {
    # full_name/mobile here are the admin's own account fields
    # (routes/auth.py's register()) - added once that write path was found
    # to still be bypassing normalization (see docs/CHANGELOG.md).
    "admins": ("admin_id", {
        "full_name": normalize_name,
        "mobile": normalize_phone,
    }),
    "enquiries": ("enquiry_id", {
        "full_name": normalize_name,
        "mobile": normalize_phone,
        "purpose": normalize_category,
        "preferred_shift": normalize_category,
        "remarks": normalize_free_text,
    }),
    "students": ("student_id", {
        "full_name": normalize_name,
        "mobile": normalize_phone,
        "address": normalize_free_text,
        "purpose": normalize_category,
        "shift": normalize_category,
    }),
    "memberships": ("membership_id", {
        "plan_name": normalize_category,
        "remarks": normalize_free_text,
    }),
    # payment_mode here only ever feeds the `payments` table itself - the
    # matching Cashbook automatic-entry column (`cashbook.payment_method`)
    # is a separate, out-of-scope concept (see database/payment_queries.py's
    # record_payment()) and is deliberately not touched by this migration.
    "payments": ("payment_id", {
        "payment_mode": normalize_category,
        "remarks": normalize_free_text,
    }),
    "library_settings": ("admin_id", {
        "owner_name": normalize_name,
        "phone": normalize_phone,
        "city": normalize_location,
        "state": normalize_location,
        "address": normalize_free_text,
        "receipt_footer": normalize_free_text,
    }),
    # category/payment_method are deliberately NOT listed here - see
    # ADR-36/TD-48 in docs/DECISIONS.md / docs/11_FUTURE_WORK.md for why
    # Cashbook's own category/payment-method fields stay excluded from this
    # migration (and from every write path) entirely.
    "cashbook": ("entry_id", {
        "person": normalize_name,
        "description": normalize_free_text,
    }),
}


_PAGE_SIZE = 1000
_MAX_ATTEMPTS = 4
_REFRESH_EVERY = 300  # rows written, not just requests


def _fresh_client():
    """A new Supabase client, not the process-wide cached singleton -
    long-running scripts that make thousands of sequential requests need a
    new underlying HTTP/2 connection periodically (see module docstring for
    the live connection-termination this avoids); the app's own request
    handlers should keep using the cached `get_supabase_client()` as normal,
    this script is the only caller that clears it."""

    get_supabase_client.cache_clear()
    return get_supabase_client()


def _with_retry(call):
    """Retry a Supabase call up to _MAX_ATTEMPTS times with a short backoff
    on transient network/HTTP failures - long-running pagination over
    thousands of rows is exactly the shape that trips a mid-run connection
    drop (see module docstring), and a single unretried failure shouldn't
    lose all the pages already processed before it."""

    last_error = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return call()
        except (APIError, Exception) as error:  # noqa: BLE001 - network/HTTP errors surface as plain Exception via httpx/httpcore, not just APIError
            last_error = error
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last_error


def _normalize_table(table, pk, field_rules):
    """Paginates through every row via `.range()` instead of one unbounded
    `.select("*").execute()` - PostgREST (Supabase's REST layer) caps an
    unranged select at its configured max-rows (1000 on this project), so a
    single unranged call silently truncates any table larger than that
    instead of raising an error. Ordering by `pk` keeps each page's window
    stable across requests, including while earlier pages are being
    written back to.

    Each changed row is written back with its own targeted `.update()` -
    see the module docstring for why a bulk `.upsert()` isn't safe here.
    """

    supabase = _fresh_client()
    updated = 0
    total = 0
    offset = 0
    since_refresh = 0

    while True:
        page = _with_retry(
            lambda: supabase.table(table)
            .select("*")
            .order(pk)
            .range(offset, offset + _PAGE_SIZE - 1)
            .execute()
            .data
        )
        if not page:
            break
        total += len(page)

        page_updated = 0
        for row in page:
            changes = {}
            for column, normalizer in field_rules.items():
                old_value = row.get(column)
                if old_value is None:
                    continue
                new_value = normalizer(old_value)
                if new_value != old_value:
                    changes[column] = new_value

            if changes:
                row_pk = row[pk]
                _with_retry(
                    lambda: supabase.table(table).update(changes).eq(pk, row_pk).execute()
                )
                updated += 1
                page_updated += 1
                since_refresh += 1

                if since_refresh >= _REFRESH_EVERY:
                    supabase = _fresh_client()
                    since_refresh = 0

        print(f"    {table}: page at offset {offset} - {len(page)} scanned, {page_updated} updated")

        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    return updated, total


def run():
    print("Normalizing existing records...")

    total_updated = 0
    for table, (pk, field_rules) in TABLE_RULES.items():
        updated, total = _normalize_table(table, pk, field_rules)
        total_updated += updated
        print(f"  {table}: {updated}/{total} rows updated")

    print(f"Done. {total_updated} rows updated in total.")


if __name__ == "__main__":
    run()
