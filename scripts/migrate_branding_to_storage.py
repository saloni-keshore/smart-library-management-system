"""One-off: move existing on-disk Library Profile branding images
(logo/stamp/signature) into Supabase Storage (ADR-57).

Run this once against a deployment that already had images uploaded under
`static/uploads/settings/` before the Storage migration (e.g. the Render
deployment). For each `library_settings` row whose `logo_path` /
`stamp_path` / `signature_path` is still a relative path AND whose file
exists on this machine, it uploads the file via
`database.branding_storage.upload_branding_image()` and rewrites the column
to the new public URL.

Idempotent: rows already holding an `http(s)://` URL, and paths whose local
file is missing, are skipped. Read-only-safe to run repeatedly.

    python scripts/migrate_branding_to_storage.py           # dry run
    python scripts/migrate_branding_to_storage.py --apply    # actually write

Standalone operator tool, same convention as scripts/verify_schema.py: not
imported by the app, not covered by pytest, inserts the repo root on
sys.path itself.
"""

import argparse
import mimetypes
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.branding_storage import upload_branding_image  # noqa: E402
from database.supabase_client import get_supabase_client  # noqa: E402

_FIELDS = ("logo_path", "stamp_path", "signature_path")
_STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"


def _is_url(value):
    return bool(value) and value.startswith(("http://", "https://"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="actually upload and rewrite rows (default: dry run)",
    )
    args = parser.parse_args()

    supabase = get_supabase_client()
    rows = supabase.table("library_settings").select("admin_id", *_FIELDS).execute().data

    migrated = skipped = missing = 0

    for row in rows:
        updates = {}
        for field in _FIELDS:
            value = row.get(field)
            if not value or _is_url(value):
                skipped += 1
                continue

            local = _STATIC_ROOT / value
            if not local.is_file():
                print(f"  admin {row['admin_id']} {field}: local file not found ({value}) - skip")
                missing += 1
                continue

            content_type = mimetypes.guess_type(str(local))[0] or "application/octet-stream"
            object_path = f"admin_{row['admin_id']}/{field.replace('_path', '')}_{local.stem}{local.suffix}"

            if args.apply:
                url = upload_branding_image(object_path, local.read_bytes(), content_type)
                updates[field] = url
                print(f"  admin {row['admin_id']} {field}: {value} -> {url}")
            else:
                print(f"  admin {row['admin_id']} {field}: WOULD upload {value} ({content_type})")
            migrated += 1

        if updates:
            supabase.table("library_settings").update(updates).eq("admin_id", row["admin_id"]).execute()

    verb = "migrated" if args.apply else "to migrate"
    print(f"\n{migrated} {verb}, {missing} local file(s) missing, {skipped} already-URL/empty skipped.")
    if not args.apply and migrated:
        print("Re-run with --apply to write the changes.")


if __name__ == "__main__":
    main()
