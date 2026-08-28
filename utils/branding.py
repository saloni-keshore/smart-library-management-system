"""Resolve a stored branding-image reference to a URL an ``<img src>`` can use.

`library_settings.logo_path` / `stamp_path` / `signature_path` hold one of:
  * a full Supabase Storage public URL (``https://...``) - the format written
    by `database/branding_storage.py` since branding moved off local disk
    (ADR-57), or
  * a legacy relative path like ``uploads/settings/logo_1_ab.png`` - written
    by the old `_save_upload()` that saved to ``static/uploads/settings/``.

`branding_src()` returns the right URL for either. Kept dependency-free (no
Flask/Supabase import) so it is trivially testable and safe to call from a
Jinja global outside a request context. The legacy branch hard-codes
``/static/`` because the app never customises ``static_url_path``.
"""


def branding_src(path):
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    return "/static/" + path.lstrip("/")
