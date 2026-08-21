"""Panda (Smart Business Assistant) - a read-only, admin-scoped chat/insights
widget shown on every authenticated page
(`templates/components/panda_widget.html`).

This package is deliberately self-contained (routes/services/prompts/
intents/notifications/forecasting/insights all live here, instead of
splitting across the top-level routes/ and database/ folders the rest of
the app uses) because it's a single, independently swappable subsystem.
See ADR-43/ADR-47/ADR-48/ADR-49/ADR-50/ADR-51 in docs/DECISIONS.md and
PANDA_SPEC.md's Ask -> Analyze -> Explain -> Recommend -> Forecast
progression - all five parts of that progression are now real.

Part 1, "Ask" (ADR-47), ships a real rule/keyword-based intent classifier
(panda/intents.py) that answers recognized questions with this admin's real
revenue/occupancy/renewal data - no external AI API and no machine learning
model. Part 2, "Analyze" (ADR-48), adds admissions/purpose/student-risk
questions, reusing existing query functions verbatim. Part 3, "Explain"
(ADR-49), adds a real "why is revenue X" reply - ranked, honest contributing
factors composed from existing data, never a fabricated single cause. Part
4, "Recommend" (ADR-50), adds a real "how can I increase profit?"/"what
should I do?" reply - Business Intelligence's existing Action Center
(`get_action_items()`), reused verbatim, no new recommendation logic. Part
5, "Forecast" (ADR-51), adds a real "what's expected next month?" reply -
panda/forecasting.py now holds a simple linear trend extrapolation over this
admin's own revenue/occupancy/renewal history (plain Python, no
scikit-learn/statsmodels/prophet, still no ML), returning an honest "not
enough history yet" answer rather than a number when there isn't enough real
variation to trust. Two more topic-specific intents (ADR-52, 2026-08-20) -
student retention ("how can I retain students?") and cash management ("how
can I manage cash?") - extend Part 1's keyword coverage laterally, each
composing existing panda/insights.py wrappers into one topic-focused reply;
this is not a sixth part of the progression above, which stays closed. A
question outside all of that still falls through to panda/prompts.py's
honest placeholder reply.

Security boundary (enforced by construction, not by a runtime filter):
Panda only ever calls existing read-only query functions (database/*.py) to
build insights and replies, and its own database/panda_queries.py to
persist its own chat log. Nothing in this package writes, updates, or
deletes any library data (students/memberships/payments/cashbook/etc.),
runs SQL directly, executes arbitrary code, touches the filesystem, or
reads secrets/config. A future tool-calling layer must preserve this: give
it read-only query functions to call, never a raw SQL/eval/exec path.
"""
