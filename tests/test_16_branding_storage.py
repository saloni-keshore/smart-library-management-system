"""Branding images (logo/stamp/signature) are stored in Supabase Storage,
not on local disk (ADR-57 / TD-73). Covers the pure URL-resolution helper
and one full upload round-trip through the Library Profile form."""
import base64
import io

import httpx

from database.supabase_client import get_supabase_client
from database.branding_storage import BUCKET, delete_branding_image
from utils.branding import branding_src

# 1x1 transparent PNG - a genuinely valid image so Storage / magic-byte
# checks accept it.
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


# ---------------------------------------------------------------------------
# branding_src() - pure, no network
# ---------------------------------------------------------------------------

def test_branding_src_none_and_empty():
    assert branding_src(None) == ""
    assert branding_src("") == ""


def test_branding_src_passes_through_full_urls():
    url = "https://x.supabase.co/storage/v1/object/public/library-branding/admin_1/logo_ab.png"
    assert branding_src(url) == url
    assert branding_src("http://localhost/y.png") == "http://localhost/y.png"


def test_branding_src_resolves_legacy_relative_path():
    assert branding_src("uploads/settings/logo_1_ab.png") == "/static/uploads/settings/logo_1_ab.png"
    assert branding_src("/uploads/settings/x.png") == "/static/uploads/settings/x.png"


# ---------------------------------------------------------------------------
# Full upload round-trip through /settings/library
# ---------------------------------------------------------------------------

def test_library_profile_logo_upload_goes_to_supabase_storage(logged_in_client):
    client, admin = logged_in_client

    stored_url = None
    try:
        resp = client.post(
            "/settings/library",
            data={
                "library_name": "Storage Lib", "owner_name": "Owner", "phone": "9876500011",
                "email": "", "address": "", "city": "", "state": "", "pincode": "",
                "opening_time": "", "closing_time": "", "weekly_holiday": "", "receipt_footer": "",
                "logo": (io.BytesIO(_PNG_BYTES), "logo.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"saved successfully" in resp.data  # not the "uploads unavailable" warning

        row = (
            get_supabase_client()
            .table("library_settings")
            .select("logo_path")
            .eq("admin_id", admin["admin_id"])
            .execute()
            .data[0]
        )
        stored_url = row["logo_path"]
        assert stored_url.startswith("https://"), stored_url
        assert BUCKET in stored_url
        assert f"admin_{admin['admin_id']}/" in stored_url

        # branding_src leaves a Storage URL untouched, so the templates emit it verbatim.
        assert branding_src(stored_url) == stored_url

        fetched = httpx.get(stored_url, timeout=15)
        assert fetched.status_code == 200
        assert fetched.headers["content-type"].startswith("image/")
        assert fetched.content == _PNG_BYTES
    finally:
        if stored_url:
            delete_branding_image(stored_url)
