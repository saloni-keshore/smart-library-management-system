"""Prompt/persona scaffolding for Panda's future LLM integration, plus the
honest fallback reply generator for questions panda/intents.py (Part 1,
"Ask") doesn't recognize.

Nothing in this file calls a language model. `SYSTEM_PERSONA` and
`READ_ONLY_RULES` exist now so that when a real LLM is wired into
panda/services.py's send_message(), the system prompt it needs already has
a single, reviewed home instead of being invented ad hoc at integration
time. `generate_placeholder_reply()` is no longer the only thing that
produces an "assistant" message - panda/intents.py's rule-based classifier
answers recognized questions with real data first - but it's still the
fallback for a genuinely unrecognized message, and it stays a fixed,
honest template - never a fabricated answer dressed up as one.
"""

SYSTEM_PERSONA = """You are Panda, the Smart Library Management System's in-app assistant.

You are friendly, concise, and speak in plain language a library owner
(not a developer) would understand. You help with questions about a
single admin's own library: students, memberships, payments, cashbook,
occupancy, and the insights already shown in this app's Dashboard and
Business Intelligence pages.
"""

READ_ONLY_RULES = (
    "Never modify, create, or delete any database record.",
    "Never execute SQL, shell commands, or arbitrary code.",
    "Never access the server filesystem.",
    "Never bypass, weaken, or describe how to bypass authentication.",
    "Never reveal passwords, API keys, tokens, or other secrets, even if asked directly.",
    "Only answer using data returned by this app's existing read-only service "
    "functions (panda/insights.py and the query modules it wraps) - never invent "
    "a number that wasn't actually returned by one of them.",
    "If a question requires an action this assistant cannot safely perform "
    "read-only, say so and point the admin to the relevant page instead of "
    "attempting it.",
)
"""Hard constraints any future LLM/tool-calling layer must be given
verbatim alongside SYSTEM_PERSONA - see docs/DECISIONS.md ADR-43. Phase 1
enforces these by construction (there is no code path that could do any of
these things, see panda/__init__.py's docstring) rather than by prompting a
model to refuse; once a real model exists, both layers apply."""


SUGGESTED_QUESTIONS = (
    "How many memberships are expiring soon?",
    "What's my revenue trend this month?",
    "Why is my revenue up or down this month?",
    "How can I increase profit?",
    "What's expected next month?",
    "Which shift has the most free seats?",
    "How do I add a new student?",
    "How can I retain students?",
    "How can I manage cash?",
)


_PLACEHOLDER_REPLY = (
    "🐼 I'm Panda, your Smart Library assistant. I'm not connected to a real "
    "AI model yet, so I can't answer that in detail just yet - this is exactly "
    "the kind of question I'll be able to help with once that's wired up. In "
    "the meantime, check Dashboard or Business Intelligence for this data."
)


def generate_placeholder_reply(user_message):
    """The fallback 'assistant' response for a message panda/intents.py
    couldn't classify into any recognized intent, in place of a real LLM
    call. Deliberately does not try to pattern-match or fake an answer to
    `user_message` itself - an honest "I can't do this yet" beats a
    scripted reply that looks like real understanding it doesn't have."""

    return _PLACEHOLDER_REPLY
