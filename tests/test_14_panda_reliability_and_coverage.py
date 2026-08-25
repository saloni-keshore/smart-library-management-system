"""Regression tests for the 2026-08-24 Panda reliability + coverage pass
(post-audit): risk-scoring batching (Phase 1.1), transient-Supabase
exception handling (Phase 1.2 - the frontend classification fix, Phase 1.3,
has no Python surface to unit-test; see static/js/panda.js's own inline
comments plus this session's manual verification), the cash reply's
all-time expense label (Phase 2), the new expenses intent, the admissions/
renewals/risk keyword-coverage gaps, and the forecast/occupancy collision
fix (Phase 3).

No enhancements beyond what those phases describe - every test here either
confirms the new documented behavior or guards a specific regression this
session was warned against introducing.
"""
import httpx
import pytest
from postgrest.exceptions import APIError

from panda import intents
from tests.conftest import (
    admit_student,
    create_membership,
    get_last_enquiry_id,
    get_last_student_id,
    make_enquiry,
)


def _send(client, conversation_id, message):
    resp = client.post(
        f"/panda/conversations/{conversation_id}/messages",
        json={"message": message},
    )
    assert resp.status_code == 201
    return resp.get_json()["assistant_message"]["content"]


def _create_conversation(client):
    resp = client.post("/panda/conversations")
    if resp.status_code == 503:
        pytest.skip("panda_conversations/panda_messages tables not yet created on this Supabase project")
    assert resp.status_code == 201
    return resp.get_json()["conversation"]["conversation_id"]


# ---------------------------------------------------------------------------
# Phase 1.1 - risk-scoring batching (database/ai_center_queries.py)
# ---------------------------------------------------------------------------

def test_batch_risk_scoring_matches_single_student_scoring_exactly(logged_in_client):
    """compute_student_risk_batch() must be a faithful optimization, not an
    approximation - every field of its result for a real student must match
    compute_student_risk()'s result for that same student exactly. Seeds one
    real student with a partially-unpaid membership (a real payment-delay
    signal) so the comparison isn't just two empty/zero results agreeing by
    coincidence."""
    from database.ai_center_queries import compute_student_risk, compute_student_risk_batch
    from database.membership_queries import get_admin_students

    client, admin = logged_in_client
    admin_id = admin["admin_id"]

    make_enquiry(client)
    enquiry_id = get_last_enquiry_id(admin_id)
    admit_student(client, enquiry_id)
    student_id = get_last_student_id(admin_id)
    create_membership(client, student_id, paid_amount="100", due_amount="400")

    single = compute_student_risk(admin_id, student_id)
    batch = compute_student_risk_batch(admin_id, students=get_admin_students(admin_id))

    assert single is not None
    assert student_id in batch
    for field in ("score", "level", "reasons", "key_info"):
        assert batch[student_id][field] == single[field], f"field {field!r} diverged"


def test_batch_risk_scoring_empty_roster_returns_empty_dict(logged_in_client):
    """A fresh admin has no students - must return {} cleanly, not raise or
    fabricate a result for a nonexistent roster."""
    from database.ai_center_queries import compute_student_risk_batch

    client, admin = logged_in_client
    assert compute_student_risk_batch(admin["admin_id"]) == {}


def test_get_top_risk_students_still_respects_the_documented_cap(monkeypatch):
    """TD-60's MAX_STUDENTS_SCORED_FOR_CHAT cap must still be applied before
    scoring, unchanged by the batching fix - this test never touches
    Supabase, it only proves the cap slice still happens by asserting
    compute_student_risk_batch() is called with a roster no larger than the
    cap even when get_admin_students() would return more."""
    from panda import insights

    fake_students = [{"student_id": i, "full_name": f"S{i}"} for i in range(150)]
    captured = {}

    def fake_get_admin_students(admin_id):
        return fake_students

    def fake_batch(admin_id, students=None):
        captured["count"] = len(students)
        return {}

    monkeypatch.setattr(insights, "get_admin_students", fake_get_admin_students)
    monkeypatch.setattr(insights, "compute_student_risk_batch", fake_batch)

    insights.get_top_risk_students(admin_id=1)
    assert captured["count"] == insights.MAX_STUDENTS_SCORED_FOR_CHAT


# ---------------------------------------------------------------------------
# Phase 1.2 - transient Supabase/network exception handling
# (database/panda_queries.py)
# ---------------------------------------------------------------------------

def _raise_api_error(*args, **kwargs):
    raise APIError({"message": "relation \"panda_conversations\" does not exist", "code": "PGRST205"})


def _raise_transport_error(*args, **kwargs):
    raise httpx.RemoteProtocolError("Server disconnected")


def test_conversations_endpoint_still_returns_503_for_missing_tables(logged_in_client, monkeypatch):
    """Existing behavior (APIError -> ChatStorageUnavailable) must be
    completely unaffected by adding the new exception class alongside it."""
    client, admin = logged_in_client
    monkeypatch.setattr("database.panda_queries._table", _raise_api_error)

    resp = client.get("/panda/conversations")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "chat_storage_unavailable"


def test_conversations_endpoint_returns_distinct_503_for_transient_network_error(logged_in_client, monkeypatch):
    """A transient httpx.RemoteProtocolError (an unhandled 500 before this
    fix - see docs/CHANGELOG.md, this was caught live during the 2026-08-24
    audit) must now become a clean 503 with its own distinct error code/
    message, not the "tables were never migrated" one - telling an admin to
    ask their project owner to run CREATE TABLE statements would be wrong
    for a one-off network blip."""
    client, admin = logged_in_client
    monkeypatch.setattr("database.panda_queries._table", _raise_transport_error)

    resp = client.get("/panda/conversations")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["error"] == "chat_temporarily_unavailable"
    assert "try again" in body["message"].lower()
    assert "CREATE TABLE" not in body["message"]


def test_messages_endpoint_returns_distinct_503_for_transient_network_error(logged_in_client, monkeypatch):
    client, admin = logged_in_client
    monkeypatch.setattr("database.panda_queries._table", _raise_transport_error)

    resp = client.post("/panda/conversations/1/messages", json={"message": "hello"})
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "chat_temporarily_unavailable"


def test_add_message_raises_temporarily_unavailable_not_a_raw_500(monkeypatch):
    """Unit-level reproduction of the class of live failure caught during
    the audit: an httpx.RemoteProtocolError anywhere in add_message()'s
    Supabase calls (directly, or via its internal get_conversation() check)
    must surface as the typed ChatStorageTemporarilyUnavailable, not
    propagate as an unhandled exception that would 500."""
    from database import panda_queries

    monkeypatch.setattr(panda_queries, "_table", _raise_transport_error)

    with pytest.raises(panda_queries.ChatStorageTemporarilyUnavailable):
        panda_queries.add_message(admin_id=1, conversation_id=1, role="user", content="hi")


def test_genuine_api_error_still_distinguishable_from_transient_error():
    """The two exception classes must stay genuinely distinct types, so a
    caller (or a future one) can never accidentally treat a real "tables
    missing" condition as a retryable blip or vice versa."""
    from database.panda_queries import ChatStorageTemporarilyUnavailable, ChatStorageUnavailable

    assert not issubclass(ChatStorageTemporarilyUnavailable, ChatStorageUnavailable)
    assert not issubclass(ChatStorageUnavailable, ChatStorageTemporarilyUnavailable)


# ---------------------------------------------------------------------------
# Phase 2 - cash reply's all-time expense label
# ---------------------------------------------------------------------------

def test_cash_reply_labels_expense_breakdown_as_all_time(logged_in_client):
    """The 2026-08-24 audit flagged this as CORRECT BUT MISLEADING: the
    expense-category breakdown (all-time, no monthly figure exists - TD-61)
    used to sit unlabeled between two this-month figures. No number should
    change, only the label."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    make_enquiry(client)
    enquiry_id = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, enquiry_id)
    student_id = get_last_student_id(admin["admin_id"])
    create_membership(client, student_id, paid_amount="200", due_amount="300")

    client.post(
        "/cashbook/add",
        data={
            "transaction_type": "Expense",
            "category": "Rent",
            "amount": "1000",
            "payment_method": "Cash",
            "person": "",
            "description": "QA all-time-label test expense",
        },
        follow_redirects=True,
    )

    reply = _send(client, conversation_id, "How can I manage cash?")
    assert "top expense categories, all-time" in reply
    assert "Rent: ₹1,000" in reply
    # The real numbers must be byte-identical to before this change.
    assert "₹200 collected of ₹500 billed" in reply
    assert "₹300 in fees is still pending collection." in reply


# ---------------------------------------------------------------------------
# Phase 3.5 - dedicated expenses intent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "How much are my expenses?",
    "What are my total expenses?",
    "How much did I spend?",
    "What are my biggest expenses?",
    "Which expense category costs me the most?",
    "Are my expenses under control?",
    "How can I reduce expenses?",
    "Where is my money going?",
    "what's my expense breakdown",
    "WHICH EXPENSE CATEGORY COSTS THE MOST",
])
def test_intent_expense_variations_detected(text):
    assert intents.detect_intent(text) == intents.INTENT_EXPENSES


def test_intent_reduce_expenses_still_does_not_collide_with_retention():
    """"Reduce" is a _RETENTION_VERBS word, but "expenses" is not a
    _RETENTION_NOUNS word - must resolve to expenses, never retention,
    regardless of check order."""
    assert intents.detect_intent("How can I reduce expenses?") == intents.INTENT_EXPENSES
    assert intents.detect_intent("How can I reduce expenses?") != intents.INTENT_RETENTION


def test_expense_question_answers_honestly_for_fresh_admin(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "How much are my expenses?")
    assert "No expenses recorded yet" in reply


def test_expense_question_reports_real_expense_breakdown(logged_in_client):
    """A real manual Expense entry must surface in the expense-topic reply,
    matching the same data database/bi_queries.get_top_expense_categories()
    already computes - verified directly against that query, not just
    presence of the string."""
    from database.bi_queries import classify_expense_health, get_top_expense_categories

    client, admin = logged_in_client
    admin_id = admin["admin_id"]
    conversation_id = _create_conversation(client)

    client.post(
        "/cashbook/add",
        data={
            "transaction_type": "Expense",
            "category": "Internet Bill",
            "amount": "750",
            "payment_method": "Cash",
            "person": "",
            "description": "QA expense-intent test",
        },
        follow_redirects=True,
    )

    reply = _send(client, conversation_id, "What are my biggest expenses?")

    categories = get_top_expense_categories(admin_id)
    health = classify_expense_health(admin_id)
    top = categories[0]

    assert f"{top['category']}: ₹{top['amount']:,.0f}" in reply
    assert "all-time" in reply
    assert health["status"] in reply


def test_expense_reply_does_not_include_fee_collection_section(logged_in_client):
    """The expenses reply is deliberately narrower than the cash-management
    reply - it must not also answer the fee-collection question, which is a
    different topic (see _reply_cash_management())."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    make_enquiry(client)
    enquiry_id = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, enquiry_id)
    student_id = get_last_student_id(admin["admin_id"])
    create_membership(client, student_id, paid_amount="200", due_amount="300")

    reply = _send(client, conversation_id, "How can I reduce expenses?")
    assert "billed" not in reply
    assert "collection rate" not in reply


# ---------------------------------------------------------------------------
# Phase 3.6 - natural-language coverage gaps (renewals/risk/admissions)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Who expires today?", "Who expires this week?", "Who expires soon?"])
def test_intent_renewal_present_tense_singular_detected(text):
    """"expires" (present-tense singular) was missing from the keyword list
    - only "expire"/"expiring"/"expired" worked before this fix."""
    assert intents.detect_intent(text) == intents.INTENT_RENEWALS


@pytest.mark.parametrize("text", ["Which students need attention?", "who needs attention", "students that need attention"])
def test_intent_need_attention_maps_to_risk_students(text):
    assert intents.detect_intent(text) == intents.INTENT_RISK_STUDENTS


@pytest.mark.parametrize("text,expected", [
    ("How many students do I have?", intents.INTENT_ADMISSIONS),
    ("How many active students?", intents.INTENT_ADMISSIONS),
    ("Which month had the most admissions?", intents.INTENT_ADMISSIONS),
    ("Are admissions increasing?", intents.INTENT_ADMISSIONS),
    ("Is admissions increasing?", intents.INTENT_ADMISSIONS),
])
def test_intent_admissions_coverage_gaps_closed(text, expected):
    assert intents.detect_intent(text) == expected


def test_admissions_reply_reports_total_student_count(logged_in_client):
    """Answers "how many students do I have" honestly with a real total
    headcount - a genuinely different fact from the month-over-month trend,
    not a substitute for it. Needs a real membership, not just an admitted
    student - get_admissions_trend() (get_monthly_new_memberships()) counts
    memberships, not raw student rows, so a student with no membership yet
    would leave the trend empty and short-circuit to the zero-guard before
    ever reaching the roster-count line."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    make_enquiry(client)
    enquiry_id = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, enquiry_id)
    student_id = get_last_student_id(admin["admin_id"])
    create_membership(client, student_id, paid_amount="500", due_amount="0")

    reply = _send(client, conversation_id, "How many students do I have?")
    assert "1 student(s) on your roster in total" in reply


def test_admissions_reply_roster_count_labeled_all_time(logged_in_client):
    """2026-08-25 wording fix (final pre-pilot audit): the roster-count line
    used to say "...on your roster in total" with no scope qualifier, even
    though get_student_count() counts every student ever admitted for this
    admin (get_admin_students() has no status filter - a lapsed/expired
    student is still counted). A non-technical owner asking "how many
    students do I have?" would naturally read an unqualified "total" as
    "currently enrolled," which this number is not for any library with
    real turnover. Must now explicitly say "all-time" and name lapsed
    memberships as included - the exact number is unchanged, only the
    sentence around it."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    make_enquiry(client)
    enquiry_id = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, enquiry_id)
    student_id = get_last_student_id(admin["admin_id"])
    create_membership(client, student_id, paid_amount="500", due_amount="0")

    reply = _send(client, conversation_id, "How many students do I have?")
    assert (
        "1 student(s) on your roster in total "
        "(all-time, including students with lapsed memberships)."
    ) in reply


def test_admissions_reply_zero_guard_unchanged(logged_in_client):
    """Existing exact-string contract (tests/test_11_panda.py) must survive
    this reply's broadening untouched."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "How many admissions this month?")
    assert "No admissions recorded yet" in reply


def test_admissions_reply_names_best_month_when_it_differs_from_latest(monkeypatch):
    """"Which month had the most admissions?" - answered from the same
    monthly dict get_admissions_trend() already returns in full (reads more
    of a dict Part 2 was already fetching, not a new query). Direct unit
    test against panda/intents.py's _reply_admissions(), monkeypatching
    panda/insights.py's two wrappers - deterministic and avoids needing to
    seed real memberships across two different real calendar months."""
    from panda import insights, intents

    monkeypatch.setattr(insights, "get_admissions_trend", lambda admin_id: {
        "2026-06": 9, "2026-07": 3, "2026-08": 5,
    })
    monkeypatch.setattr(insights, "get_student_count", lambda admin_id: 17)

    reply = intents._reply_admissions(admin_id=1)
    assert "Admissions are up this month: 5 new admission(s) in 2026-08 (vs 3 in 2026-07)." in reply
    assert "Your best month so far was 2026-06 with 9 new admission(s)." in reply
    assert (
        "You have 17 student(s) on your roster in total "
        "(all-time, including students with lapsed memberships)."
    ) in reply


def test_admissions_reply_omits_best_month_line_when_latest_is_best(monkeypatch):
    """No redundant "best month" line when the most recent month already is
    the best one - that fact is already conveyed by the first sentence."""
    from panda import insights, intents

    monkeypatch.setattr(insights, "get_admissions_trend", lambda admin_id: {
        "2026-07": 3, "2026-08": 9,
    })
    monkeypatch.setattr(insights, "get_student_count", lambda admin_id: 17)

    reply = intents._reply_admissions(admin_id=1)
    assert "best month" not in reply.lower()


# ---------------------------------------------------------------------------
# Phase 3.7 - forecast/occupancy collision fix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Will occupancy increase?", "will seats increase", "will my occupancy grow"])
def test_intent_forward_looking_occupancy_becomes_forecast(text):
    assert intents.detect_intent(text) == intents.INTENT_FORECAST


@pytest.mark.parametrize("text", ["What's my seat occupancy?", "Which shift has the most free seats?", "How many seats are occupied?"])
def test_intent_present_tense_occupancy_questions_unaffected(text):
    """Regression guard: only forward-looking ("will") occupancy wording
    should move to forecast - plain present-state occupancy questions must
    keep answering with the current occupancy reply, unchanged."""
    assert intents.detect_intent(text) == intents.INTENT_OCCUPANCY


@pytest.mark.parametrize("text", [
    "how will retention improve",
    "will pending fees increase",
    "will my cash flow improve",
])
def test_intent_future_occupancy_check_does_not_hijack_other_topics(text):
    """The forward-looking check is deliberately scoped to occupancy
    vocabulary only - "will" + a direction word alone must never override a
    more specific topic (retention/cash) checked later in detect_intent(),
    which a blanket "will X increase" pattern would have done."""
    assert intents.detect_intent(text) != intents.INTENT_FORECAST


def test_forward_looking_occupancy_question_gets_forecast_reply_for_fresh_admin(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "Will occupancy increase?")
    assert "don't have enough months of real history" in reply
