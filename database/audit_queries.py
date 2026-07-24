"""
Audit trail for every financial change made to the Cashbook ledger.

Supabase's `audit_log` table is the source of truth (ADR-22) - as of
2026-07-24 (Phase 10 mirror removal), it has no SQLite mirror at all.
`database/cashbook_queries.py` writes the Supabase `audit_log` row directly
for every cashbook write, next to its own Supabase `cashbook` write.
"""

from database.supabase_client import get_supabase_client


def get_recent_audit_log(admin_id, limit=15):
    """Latest financial changes for this admin, newest first.

    Reads Supabase - the source of truth for audit_log since ADR-22 - and
    attaches the admin's own full_name as `performed_by` in Python (every
    row here belongs to this one admin_id, so this is a single lookup, not
    a per-row join).
    """

    supabase = get_supabase_client()

    resp = (
        supabase.table("audit_log")
        .select("*")
        .eq("admin_id", admin_id)
        .order("created_at", desc=True)
        .order("log_id", desc=True)
        .limit(limit)
        .execute()
    )

    admin_resp = (
        supabase.table("admins")
        .select("full_name")
        .eq("admin_id", admin_id)
        .execute()
    )
    performed_by = admin_resp.data[0]["full_name"] if admin_resp.data else None

    rows = []
    for row in resp.data:
        row = dict(row)
        row["performed_by"] = performed_by
        rows.append(row)

    return rows
