"""Panda AI Assistant - a read-only, admin-scoped chat/insights widget shown
on every authenticated page (`templates/components/panda_widget.html`).

This package is deliberately self-contained (routes/services/prompts/
notifications/forecasting/insights all live here, instead of splitting
across the top-level routes/ and database/ folders the rest of the app
uses) because it's a single, independently swappable subsystem: the whole
point of this phase is that a future LLM integration only ever has to
change panda/prompts.py and panda/services.py's reply generation, without
touching routes/ or database/. See ADR-43 in docs/DECISIONS.md.

Phase 1 (this phase) ships no real AI model - see panda/forecasting.py and
panda/prompts.py's generate_placeholder_reply() for exactly what's stubbed.

Security boundary (enforced by construction, not by a runtime filter):
Panda only ever calls existing read-only query functions (database/*.py) to
build insights, and its own database/panda_queries.py to persist its own
chat log. Nothing in this package writes, updates, or deletes any library
data (students/memberships/payments/cashbook/etc.), runs SQL directly,
executes arbitrary code, touches the filesystem, or reads secrets/config.
A future tool-calling layer must preserve this: give it read-only query
functions to call, never a raw SQL/eval/exec path.
"""
