"""Supabase Storage access for Library Profile branding images
(logo / stamp / signature).

Sibling to `database/supabase_client.py`: that module is the Supabase-DB
access layer, this one is the Supabase-Storage access layer. Branding images
moved here from local disk (`static/uploads/settings/`) so uploads work on a
read-only-filesystem host (Vercel) and survive redeploys on an ephemeral one
(Render) - see ADR-57 / TD-73.

The bucket is **public** (a library logo/stamp is not sensitive and is
printed on every receipt anyway) and **auto-creates on first upload** - the
Storage REST API accepts `create_bucket` from Python with the service-role
key even though raw SQL DDL is not available (ADR-14 is about SQL, not
Storage), so no manual PROVISIONING step is needed.

What gets stored in `library_settings.*_path` is the full public URL
returned by `get_public_url()`. `utils/branding.py`'s `branding_src()`
passes those straight through and still resolves any legacy relative path.
"""

import os
from functools import lru_cache

from database.supabase_client import get_supabase_client

BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "library-branding")
_MAX_BYTES = 5 * 1024 * 1024  # keep in step with config.Config.MAX_CONTENT_LENGTH
_ALLOWED_MIME = ["image/png", "image/jpeg", "image/webp"]
_PUBLIC_MARKER = "/storage/v1/object/public/"


@lru_cache(maxsize=1)
def _ensure_bucket():
    """Create the branding bucket if it doesn't exist yet. Cached for the
    process on first success; an exception is not cached, so a transient
    failure is retried on the next call."""

    storage = get_supabase_client().storage

    try:
        storage.get_bucket(BUCKET)
        return True
    except Exception:
        pass  # not found (or transient) - try to create it below

    try:
        storage.create_bucket(
            BUCKET,
            options={
                "public": True,
                "file_size_limit": _MAX_BYTES,
                "allowed_mime_types": _ALLOWED_MIME,
            },
        )
    except Exception:
        # Most likely a race with another worker that just created it -
        # confirm it exists now, and let a genuine failure propagate.
        storage.get_bucket(BUCKET)

    return True


def upload_branding_image(object_path, data, content_type):
    """Upload `data` (bytes) to `object_path` in the branding bucket and
    return its full public URL (to store in `library_settings`)."""

    _ensure_bucket()
    storage = get_supabase_client().storage.from_(BUCKET)
    storage.upload(
        object_path,
        data,
        {"content-type": content_type, "cache-control": "3600", "upsert": "true"},
    )
    return storage.get_public_url(object_path)


def _object_path_from(url_or_path):
    """The in-bucket object path for a stored value, or None if it isn't a
    Storage URL for our bucket (e.g. a legacy `uploads/settings/...` path)."""

    marker = _PUBLIC_MARKER + BUCKET + "/"
    if marker in url_or_path:
        return url_or_path.split(marker, 1)[1].split("?", 1)[0]
    return None


def delete_branding_image(url_or_path):
    """Best-effort removal of a previously stored branding image. Never
    raises - a failed cleanup must not break the request that triggered it."""

    if not url_or_path:
        return

    object_path = _object_path_from(url_or_path)
    if object_path is None:
        # Legacy local file - try to unlink it (works on Render, no-op on a
        # read-only host). Imported lazily so this module needs no Flask.
        try:
            import os as _os

            from flask import current_app

            legacy = _os.path.join(current_app.static_folder, url_or_path)
            if _os.path.exists(legacy):
                _os.remove(legacy)
        except Exception:
            pass
        return

    try:
        get_supabase_client().storage.from_(BUCKET).remove([object_path])
    except Exception:
        pass
