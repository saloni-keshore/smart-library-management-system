"""Admin-isolated persistence for the Panda AI Assistant's chat history
(`panda/` blueprint package, ADR-43) - conversations and their messages.

`panda_conversations`/`panda_messages` are brand-new tables, not yet
applicable by this app itself - see the CREATE TABLE statements' comment in
database/supabase_migration.sql and ADR-43 for why (this app has no DDL
path, ADR-14/38). Every function here raises ChatStorageUnavailable if
either table doesn't exist yet on the connected Supabase project; callers
(panda/routes.py) catch that to return a clear 503 instead of a 500 - the
rest of Panda (insights, suggested questions) does not depend on these
tables and keeps working regardless.

Every read/write is scoped to a single admin_id, and conversation ownership
is enforced as part of the query itself (`.eq("admin_id", admin_id)`), not
just checked afterwards in Python - the same cross-tenant-isolation shape
every other *_queries.py module in this app uses.
"""

from postgrest.exceptions import APIError

from database.settings_queries import _now_iso
from database.supabase_client import get_supabase_client


class ChatStorageUnavailable(Exception):
    """Raised when panda_conversations/panda_messages don't exist yet on
    this Supabase project. Distinct from "conversation not found" (which is
    a normal, expected 404 - the tables exist, this admin just doesn't own
    that id)."""


def _table(name):
    return get_supabase_client().table(name)


def create_conversation(admin_id, title=None):
    """Starts a new, empty conversation owned by admin_id. Title is left
    NULL until the first user message arrives (add_message auto-titles it)."""

    try:
        response = _table("panda_conversations").insert({
            "admin_id": admin_id,
            "title": title,
            "updated_at": _now_iso(),
        }).execute()
    except APIError as exc:
        raise ChatStorageUnavailable from exc

    return response.data[0]


def list_conversations(admin_id):
    """This admin's conversations, most recently active first."""

    try:
        response = (
            _table("panda_conversations")
            .select("conversation_id, title, created_at, updated_at")
            .eq("admin_id", admin_id)
            .order("updated_at", desc=True)
            .execute()
        )
    except APIError as exc:
        raise ChatStorageUnavailable from exc

    return response.data


def get_conversation(admin_id, conversation_id):
    """This admin's own conversation row, or None - either it doesn't
    exist, or it belongs to a different admin (both look identical to the
    caller, which is the point: no cross-tenant existence leak)."""

    try:
        response = (
            _table("panda_conversations")
            .select("conversation_id, title, created_at, updated_at")
            .eq("conversation_id", conversation_id)
            .eq("admin_id", admin_id)
            .execute()
        )
    except APIError as exc:
        raise ChatStorageUnavailable from exc

    return response.data[0] if response.data else None


def get_messages(admin_id, conversation_id):
    """Every message in this conversation, oldest first - or None if this
    admin doesn't own (or the id doesn't match) a conversation."""

    conversation = get_conversation(admin_id, conversation_id)
    if conversation is None:
        return None

    try:
        response = (
            _table("panda_messages")
            .select("message_id, role, content, created_at")
            .eq("conversation_id", conversation_id)
            .order("message_id", desc=False)
            .execute()
        )
    except APIError as exc:
        raise ChatStorageUnavailable from exc

    return response.data


def add_message(admin_id, conversation_id, role, content):
    """Appends one message to a conversation this admin owns, bumps the
    conversation's updated_at, and - the first time a 'user' message lands
    on a still-untitled conversation - sets the title from it, so the chat
    history list has something readable without a real AI ever having
    summarized anything. Returns the new message row, or None if this admin
    doesn't own the conversation."""

    conversation = get_conversation(admin_id, conversation_id)
    if conversation is None:
        return None

    try:
        response = _table("panda_messages").insert({
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
        }).execute()

        update = {"updated_at": _now_iso()}
        if role == "user" and not conversation.get("title"):
            update["title"] = content[:60]

        _table("panda_conversations").update(update).eq("conversation_id", conversation_id).execute()
    except APIError as exc:
        raise ChatStorageUnavailable from exc

    return response.data[0]
