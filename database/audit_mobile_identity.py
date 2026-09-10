"""
Read-only audit: check that every enquiry/student mobile is a valid
canonical 10-digit number and that no two *students* of the same library
share one (the "one phone number = one person per library" rule - ADR-58,
backed by `students.UNIQUE(mobile, admin_id)` in
`database/supabase_migration.sql`).

This script NEVER writes. It only reads and prints. It exists because the
`UNIQUE(mobile, admin_id)` constraint declared in the schema is not
guaranteed to have been applied on every deployed Supabase project (same
class of gap as TD-83), so real duplicate rows can already be sitting in
the data. Run it to see exactly what needs a hand-correction before the
constraint can be turned on.

Run from the project root:
    python -m database.audit_mobile_identity

What it reports, per `admin_id`:
  * INVALID  - a `mobile` that `utils.normalization.clean_mobile()` cannot
    reduce to 10 digits (wrong length, contains letters, etc.). These are
    legacy rows written before the 10-digit rule (ADR-59) existed - the
    current forms reject such input.
  * DUPLICATE (students) - a `(admin_id, clean_mobile)` shared by more than
    one `students` row. This is a genuine data-integrity violation and
    must be resolved (one real number per person) before
    `ALTER TABLE students ADD CONSTRAINT students_mobile_admin_id_key
    UNIQUE (mobile, admin_id);` can be applied.
  * DUPLICATE (enquiries) - the same, for `enquiries`. Informational only:
    ADR-58 deliberately keeps enquiry uniqueness app-level (no DB
    constraint), enforced by `_find_person_by_mobile()`.
  * CROSS (enquiry vs student, different names) - one canonical number
    attached to an enquiry and a student whose names don't match. Usually
    benign (a name was corrected on one side after admission), listed so a
    real mismatch isn't missed.

Paginates via `.range()` (PostgREST caps an unranged select at 1000 rows on
this project - see `database/migrate_normalize_input_data.py`) and retries
transient network failures, since a full table scan is exactly the shape
that trips a mid-run connection drop.
"""

import time
from collections import defaultdict

from postgrest.exceptions import APIError

from database.supabase_client import get_supabase_client
from utils.normalization import clean_mobile

_PAGE_SIZE = 1000
_MAX_ATTEMPTS = 4


def _fresh_client():
    """A new client, not the process-wide cached singleton - a long scan of
    several tables benefits from a fresh HTTP/2 connection (see
    `database/migrate_normalize_input_data.py` for the live connection drop
    this avoids)."""
    get_supabase_client.cache_clear()
    return get_supabase_client()


def _with_retry(call):
    """Retry a Supabase call a few times with backoff on transient
    network/HTTP failures."""
    last_error = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return call()
        except (APIError, Exception) as error:  # noqa: BLE001 - httpx/httpcore errors surface as plain Exception
            last_error = error
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last_error


def _scan(table, columns):
    """Return every row of `table` (all admins), paginated. Read-only."""
    supabase = _fresh_client()
    rows = []
    offset = 0
    while True:
        page = _with_retry(
            lambda: supabase.table(table)
            .select(columns)
            .order("admin_id")
            .range(offset, offset + _PAGE_SIZE - 1)
            .execute()
            .data
        )
        if not page:
            break
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return rows


def _invalid_rows(rows, id_key, name_key):
    """Rows whose stored mobile can't canonicalize to 10 digits."""
    out = []
    for r in rows:
        raw = r.get("mobile")
        if not clean_mobile(raw):
            out.append((r["admin_id"], r[id_key], r.get(name_key), raw))
    return out


def _duplicate_groups(rows, id_key, name_key):
    """`(admin_id, clean_mobile) -> [(id, name, raw), ...]` for every
    canonical number that appears on more than one row of the same admin.
    Rows with an invalid mobile are skipped (they're reported separately)."""
    groups = defaultdict(list)
    for r in rows:
        clean = clean_mobile(r.get("mobile"))
        if not clean:
            continue
        groups[(r["admin_id"], clean)].append(
            (r[id_key], r.get(name_key), r.get("mobile"))
        )
    return {key: members for key, members in groups.items() if len(members) > 1}


def _print_invalid(label, invalid):
    print(f"\n--- INVALID mobile numbers in {label} ({len(invalid)}) ---")
    if not invalid:
        print("  (none)")
        return
    for admin_id, row_id, name, raw in sorted(invalid):
        print(f"  admin {admin_id} | #{row_id} | {name!r} | stored mobile {raw!r}")


def _print_duplicates(label, dupes):
    print(f"\n--- DUPLICATE {label} phone numbers ({len(dupes)} number(s)) ---")
    if not dupes:
        print("  (none)")
        return
    for (admin_id, clean), members in sorted(dupes.items()):
        print(f"  admin {admin_id} | {clean} | {len(members)} rows:")
        for row_id, name, raw in members:
            print(f"      #{row_id} | {name!r} | stored {raw!r}")


def run():
    print("Auditing mobile-number identity (read-only, no writes)...")

    students = _scan("students", "student_id, admin_id, enquiry_id, full_name, mobile, status")
    enquiries = _scan("enquiries", "enquiry_id, admin_id, full_name, mobile, status")
    print(f"Scanned {len(students)} students, {len(enquiries)} enquiries.")

    student_invalid = _invalid_rows(students, "student_id", "full_name")
    enquiry_invalid = _invalid_rows(enquiries, "enquiry_id", "full_name")
    student_dupes = _duplicate_groups(students, "student_id", "full_name")
    enquiry_dupes = _duplicate_groups(enquiries, "enquiry_id", "full_name")

    _print_invalid("students", student_invalid)
    _print_invalid("enquiries", enquiry_invalid)
    _print_duplicates("students (BLOCKS the UNIQUE constraint)", student_dupes)
    _print_duplicates("enquiries (informational - ADR-58, no DB constraint)", enquiry_dupes)

    # Cross-table: same canonical number on an enquiry and a student whose
    # names disagree. Mostly benign; surfaced so a real mismatch isn't lost.
    student_by_key = {}
    for r in students:
        clean = clean_mobile(r.get("mobile"))
        if clean:
            student_by_key.setdefault((r["admin_id"], clean), []).append(r)
    mismatches = []
    for r in enquiries:
        clean = clean_mobile(r.get("mobile"))
        if not clean:
            continue
        for s in student_by_key.get((r["admin_id"], clean), []):
            e_name = (r.get("full_name") or "").strip().lower()
            s_name = (s.get("full_name") or "").strip().lower()
            if e_name != s_name:
                mismatches.append(
                    (r["admin_id"], clean, r["enquiry_id"], r.get("full_name"),
                     s["student_id"], s.get("full_name"))
                )
    print(f"\n--- CROSS enquiry vs student, name differs ({len(mismatches)}) ---")
    if not mismatches:
        print("  (none)")
    for admin_id, clean, enq_id, enq_name, stu_id, stu_name in sorted(mismatches):
        print(f"  admin {admin_id} | {clean} | enquiry #{enq_id} {enq_name!r} "
              f"vs student #{stu_id} {stu_name!r}")

    print("\n--- SUMMARY ---")
    print(f"  students with an invalid mobile : {len(student_invalid)}")
    print(f"  enquiries with an invalid mobile: {len(enquiry_invalid)}")
    print(f"  duplicate student numbers       : {len(student_dupes)}  "
          f"<- must be 0 before adding UNIQUE(mobile, admin_id)")
    print(f"  duplicate enquiry numbers       : {len(enquiry_dupes)}")
    print(f"  enquiry/student name mismatches  : {len(mismatches)}")
    print("\nNo data was modified.")


if __name__ == "__main__":
    run()
