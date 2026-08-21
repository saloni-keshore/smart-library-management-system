"""Orchestration layer between panda/routes.py and everything else - the
one place that decides how insights, suggested questions, and chat
persistence fit together. Routes stay thin (parse the request, call one of
these, shape the JSON response); nothing here touches `request`/`session`
directly, so it stays testable and reusable if a second entry point (e.g. a
future mobile API) ever needs the same behavior.
"""

from database import panda_queries
from panda import intents, notifications, prompts


def get_today_insights(admin_id):
    """Cards for the "Today's AI Insights" section - see
    panda/notifications.py for what triggers each one."""

    return notifications.get_notifications(admin_id)


def get_suggested_questions(admin_id):
    """Static conversation-starter chips shown when a chat is empty. Not
    yet personalized per admin (that needs a real model) - see
    panda/prompts.py's SUGGESTED_QUESTIONS."""

    return list(prompts.SUGGESTED_QUESTIONS)


def list_conversations(admin_id):
    return panda_queries.list_conversations(admin_id)


def start_conversation(admin_id):
    return panda_queries.create_conversation(admin_id)


def get_conversation_thread(admin_id, conversation_id):
    """The conversation's own metadata plus its full message list, or None
    if this admin doesn't own that conversation id."""

    conversation = panda_queries.get_conversation(admin_id, conversation_id)
    if conversation is None:
        return None

    messages = panda_queries.get_messages(admin_id, conversation_id)
    return {"conversation": conversation, "messages": messages}


def send_message(admin_id, conversation_id, text):
    """Persists the admin's message, then persists and returns Panda's
    reply to it - a real, rule-based intent classification and answer
    (see panda/intents.py) for recognized questions, or prompts.py's honest
    placeholder for anything it doesn't recognize yet. Returns None if this
    admin doesn't own conversation_id."""

    user_message = panda_queries.add_message(admin_id, conversation_id, "user", text)
    if user_message is None:
        return None

    reply_text = intents.generate_reply(admin_id, text)
    assistant_message = panda_queries.add_message(admin_id, conversation_id, "assistant", reply_text)

    return {"user_message": user_message, "assistant_message": assistant_message}
