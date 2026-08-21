"""HTTP surface for the Panda AI Assistant widget - every endpoint is JSON,
called by static/js/panda.js from the floating widget on every
authenticated page (templates/components/panda_widget.html).

Every route requires a logged-in admin (session["admin_id"]) and returns a
401 JSON body instead of redirecting, since these are all fetch() calls
from a widget, not page navigations - same shape as routes/ai_center.py's
student_suggestions() JSON endpoint. Every read/write below is scoped to
the logged-in admin_id; conversation ownership is enforced inside
database/panda_queries.py itself, not just checked here.
"""

from flask import Blueprint, jsonify, request, session

from database.panda_queries import ChatStorageUnavailable
from panda import services

panda_bp = Blueprint("panda", __name__, url_prefix="/panda")

MAX_MESSAGE_LENGTH = 2000

CHAT_UNAVAILABLE_RESPONSE = {
    "error": "chat_storage_unavailable",
    "message": (
        "Chat history isn't set up yet on this account - ask your project "
        "owner to run the panda_conversations/panda_messages CREATE TABLE "
        "statements in database/supabase_migration.sql."
    ),
}


def _require_admin():
    return session.get("admin_id")


@panda_bp.route("/insights")
def insights():
    admin_id = _require_admin()
    if not admin_id:
        return jsonify({"error": "unauthorized"}), 401

    return jsonify({"insights": services.get_today_insights(admin_id)})


@panda_bp.route("/suggested-questions")
def suggested_questions():
    admin_id = _require_admin()
    if not admin_id:
        return jsonify({"error": "unauthorized"}), 401

    return jsonify({"questions": services.get_suggested_questions(admin_id)})


@panda_bp.route("/conversations", methods=["GET", "POST"])
def conversations():
    admin_id = _require_admin()
    if not admin_id:
        return jsonify({"error": "unauthorized"}), 401

    try:
        if request.method == "POST":
            return jsonify({"conversation": services.start_conversation(admin_id)}), 201

        return jsonify({"conversations": services.list_conversations(admin_id)})
    except ChatStorageUnavailable:
        return jsonify(CHAT_UNAVAILABLE_RESPONSE), 503


@panda_bp.route("/conversations/<int:conversation_id>/messages", methods=["GET", "POST"])
def messages(conversation_id):
    admin_id = _require_admin()
    if not admin_id:
        return jsonify({"error": "unauthorized"}), 401

    try:
        if request.method == "POST":
            raw_message = (request.get_json(silent=True) or {}).get("message")
            text = raw_message.strip() if isinstance(raw_message, str) else ""
            if not text:
                return jsonify({"error": "empty_message"}), 400
            if len(text) > MAX_MESSAGE_LENGTH:
                return jsonify({"error": "message_too_long"}), 400

            result = services.send_message(admin_id, conversation_id, text)
            if result is None:
                return jsonify({"error": "not_found"}), 404
            return jsonify(result), 201

        thread = services.get_conversation_thread(admin_id, conversation_id)
        if thread is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(thread)
    except ChatStorageUnavailable:
        return jsonify(CHAT_UNAVAILABLE_RESPONSE), 503
