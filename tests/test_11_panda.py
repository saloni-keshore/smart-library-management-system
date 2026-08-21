"""Panda / Smart Business Assistant - architecture + persistence (ADR-43),
plus Part 1's real rule-based intent classifier and replies (ADR-47).

panda_conversations/panda_messages are brand-new Supabase tables this app
cannot create itself (same shape as ai_center_settings, see
database/panda_queries.py) - chat-persistence tests below skip themselves
if the connected Supabase project doesn't have them yet. Insights,
suggested questions, and every validation/auth-guard check don't depend on
those tables and always run for real.
"""
import datetime

import pytest

from panda import intents
from tests.conftest import (
    admit_student,
    create_membership,
    get_admin_by_username,
    get_last_enquiry_id,
    get_last_student_id,
    make_enquiry,
)


# ---------------------------------------------------------------------------
# Intent classification - pure unit tests, no Flask/DB needed (ADR-47)
# ---------------------------------------------------------------------------

def test_intent_word_boundary_ignores_hi_inside_another_word():
    """Regression guard: "which" contains the substring "hi", but must not
    be misclassified as a greeting - detect_intent matches whole
    words/phrases only, via panda/intents.py's _normalize()."""
    assert intents.detect_intent("Which locality gives me the highest admissions?") == intents.INTENT_UNKNOWN


def test_intent_action_request_beats_revenue_recommend_wording():
    """"Increase all membership fees" contains "increase", which also
    appears in the recommend keyword list - the pricing-verb + pricing-noun
    action check must still win, since misclassifying an action request as
    an answerable question is the security-relevant mistake."""
    assert intents.detect_intent("Increase all membership fees") == intents.INTENT_ACTION_REQUEST


def test_intent_deletion_request_detected():
    assert intents.detect_intent("Delete Rahul Sharma") == intents.INTENT_ACTION_REQUEST


def test_intent_increase_profit_is_recommend_not_action():
    """"increase" alone (no fee/price/rate noun) must not trigger the
    action-request guard."""
    assert intents.detect_intent("How can I increase profit?") == intents.INTENT_RECOMMEND


@pytest.mark.parametrize("text,expected", [
    ("What's my revenue trend this month?", intents.INTENT_REVENUE),
    ("How's my seat occupancy?", intents.INTENT_OCCUPANCY),
    ("Which shift has the most free seats?", intents.INTENT_OCCUPANCY),
    ("Any memberships expiring soon?", intents.INTENT_RENEWALS),
    ("Which students are likely to leave?", intents.INTENT_RISK_STUDENTS),
    ("What is expected next month?", intents.INTENT_FORECAST),
    ("How do I add a new student?", intents.INTENT_NAV_HELP),
    ("Hello", intents.INTENT_GREETING),
    ("How many students do I have?", intents.INTENT_UNKNOWN),
    ("How many admissions this month?", intents.INTENT_ADMISSIONS),
    ("What's my admissions trend?", intents.INTENT_ADMISSIONS),
    ("Best performing course?", intents.INTENT_PURPOSE_PERFORMANCE),
    ("Which batch should I promote?", intents.INTENT_PURPOSE_PERFORMANCE),
])
def test_intent_detection_examples(text, expected):
    assert intents.detect_intent(text) == expected


def test_intent_locality_admissions_question_stays_unknown():
    """"the highest admissions" must not trigger the admissions-trend intent
    - there's no locality/city data anywhere in this schema (see
    PANDA_SPEC.md), so answering with a real-but-locality-less trend would
    be answering a different question than the one actually asked."""
    assert intents.detect_intent("Which locality gives me the highest admissions?") == intents.INTENT_UNKNOWN


@pytest.mark.parametrize("text", [
    "Why is my revenue decreasing?",
    "Why is revenue up this month?",
    "What's the reason for my income drop?",
    "Can you explain my revenue?",
])
def test_intent_explain_revenue_detected(text):
    assert intents.detect_intent(text) == intents.INTENT_EXPLAIN_REVENUE


def test_intent_explain_revenue_beats_plain_revenue_wording():
    """"Why is my revenue X" also contains "revenue" (a plain-revenue
    keyword) - the more specific explain intent must win, same "more
    specific answerable intent wins" rule as the batch/purpose case below."""
    assert intents.detect_intent("Why is my revenue trending down?") == intents.INTENT_EXPLAIN_REVENUE


def test_intent_plain_revenue_question_without_why_stays_revenue():
    assert intents.detect_intent("What's my revenue trend this month?") == intents.INTENT_REVENUE


def test_intent_batch_question_beats_recommend_should_i_wording():
    """"Which batch should I promote?" contains "should i" (a recommend
    keyword) - the more specific, answerable purpose-performance intent
    must win, per the user's explicit decision to answer batch questions
    with real purpose data rather than the generic "not built yet" reply."""
    assert intents.detect_intent("Which batch should I promote?") == intents.INTENT_PURPOSE_PERFORMANCE


@pytest.mark.parametrize("text", [
    "What's expected next month?",
    "Can you forecast my revenue?",
    "Give me a prediction for next week",
    "What's my revenue outlook?",
    "What should I expect in the coming month?",
    "Any projection for the upcoming month?",
    "What's expected in the next 30 days?",
])
def test_intent_forecast_variations_detected(text):
    assert intents.detect_intent(text) == intents.INTENT_FORECAST


def test_intent_forecast_beats_churn_risk_wording():
    """"Predict membership churn next month" contains "churn" (a
    risk-list keyword since Part 2) - Part 5's forecast wording must win,
    since this is asking for the real aggregate trend projection
    (panda/forecasting.forecast_membership_churn()), not Part 2's
    per-student High-risk list. See ADR-51."""
    assert intents.detect_intent("Predict membership churn next month") == intents.INTENT_FORECAST


def test_intent_plain_churn_question_without_forecast_wording_stays_risk():
    """Without any forecast wording, "churn" still correctly falls through
    to the real Part 2 per-student risk list, unchanged by Part 5."""
    assert intents.detect_intent("Which students are at risk of churning?") == intents.INTENT_RISK_STUDENTS


# ---------------------------------------------------------------------------
# Retention / cash-management intents (ADR-52) - topic-expansion keyword
# coverage, not a sixth part of the Ask->Analyze->Explain->Recommend->
# Forecast progression.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "How can I retain students?",
    "How do I reduce churn?",
    "How can I keep students longer?",
    "How can I improve student retention?",
    "What can I do to stop students leaving?",
])
def test_intent_retention_variations_detected(text):
    assert intents.detect_intent(text) == intents.INTENT_RETENTION


def test_intent_retention_beats_churn_risk_wording():
    """"How do I reduce churn?" contains the bare word "churn" (a
    _RISK_PHRASES keyword) - the retention-topic reply is the more
    specific answer to what was actually asked, same collision-avoidance
    shape ADR-51 already established for forecast-vs-risk."""
    assert intents.detect_intent("How do I reduce churn?") == intents.INTENT_RETENTION


def test_intent_plain_risk_question_without_retention_wording_stays_risk():
    """Regression guard: a bare risk question (no retention-flavored verb)
    must still reach the real Part 2 per-student risk list, unchanged."""
    assert intents.detect_intent("Which students are at risk of leaving?") == intents.INTENT_RISK_STUDENTS


def test_intent_reduce_expenses_does_not_become_retention():
    """"Reduce" alone (no churn/leaving/dropout noun) must not trigger
    retention - "expenses" isn't a retention-topic noun, and this phrasing
    doesn't match any other intent either, so it honestly stays unknown."""
    assert intents.detect_intent("How can I reduce expenses?") == intents.INTENT_UNKNOWN


@pytest.mark.parametrize("text", [
    "How can I manage cash?",
    "How is my cash flow?",
    "How can I improve cash collection?",
    "Where is my cash going?",
    "How can I reduce pending fees?",
])
def test_intent_cash_variations_detected(text):
    assert intents.detect_intent(text) == intents.INTENT_CASH


# ---------------------------------------------------------------------------
# panda/forecasting.py's math - pure unit tests, no Flask/DB needed (ADR-51)
# ---------------------------------------------------------------------------

def test_linear_forecast_projects_a_steady_upward_trend():
    from panda import forecasting
    assert forecasting._linear_forecast([100, 110, 120], months_ahead=1) == 130.0


def test_linear_forecast_projects_further_ahead():
    from panda import forecasting
    assert forecasting._linear_forecast([100, 110, 120], months_ahead=2) == 140.0


def test_linear_forecast_flat_series_projects_the_same_value():
    from panda import forecasting
    assert forecasting._linear_forecast([50, 50, 50, 50], months_ahead=1) == 50.0


@pytest.mark.parametrize("values,expected", [
    ([100, 110, 120], "up"),
    ([120, 110, 100], "down"),
    ([100, 100, 100], "flat"),
])
def test_trend_direction(values, expected):
    from panda import forecasting
    assert forecasting._trend_direction(values) == expected


def _register_and_login(client, suffix):
    import random
    import string

    creds = {
        "full_name": f"Panda Tester {suffix}",
        "username": f"qa_panda_{suffix}",
        "mobile": "9" + "".join(random.choices(string.digits, k=9)),
        "email": f"panda_{suffix}@example.com",
        "password": "PandaPass1",
        "confirm_password": "PandaPass1",
    }
    client.post("/register", data=creds, follow_redirects=True)
    client.post("/", data={"username": creds["username"], "password": creds["password"]}, follow_redirects=True)
    creds["admin_id"] = get_admin_by_username(creds["username"])["admin_id"]
    return creds


def _create_conversation(client):
    resp = client.post("/panda/conversations")
    if resp.status_code == 503:
        pytest.skip("panda_conversations/panda_messages tables not yet created on this Supabase project")
    assert resp.status_code == 201
    return resp.get_json()["conversation"]["conversation_id"]


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def test_insights_requires_login(client):
    resp = client.get("/panda/insights")
    assert resp.status_code == 401


def test_suggested_questions_requires_login(client):
    resp = client.get("/panda/suggested-questions")
    assert resp.status_code == 401


def test_conversations_list_requires_login(client):
    resp = client.get("/panda/conversations")
    assert resp.status_code == 401


def test_conversations_create_requires_login(client):
    resp = client.post("/panda/conversations")
    assert resp.status_code == 401


def test_messages_requires_login(client):
    resp = client.get("/panda/conversations/1/messages")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Insights + suggested questions
# ---------------------------------------------------------------------------

def test_insights_for_fresh_admin_only_flags_empty_seats(logged_in_client):
    """A brand-new admin has no revenue drop and no expiring memberships,
    but does have the default seating capacity (see
    database/bi_queries.py's get_shift_capacities) sitting at 0% occupied -
    genuinely underutilized, so panda/notifications.py's shift-utilization
    check is expected to fire; the revenue/membership checks should not."""
    client, admin = logged_in_client
    resp = client.get("/panda/insights")
    assert resp.status_code == 200
    insights = resp.get_json()["insights"]
    assert [item["type"] for item in insights] == ["occupancy"]


def test_suggested_questions_returns_static_list(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/panda/suggested-questions")
    assert resp.status_code == 200
    questions = resp.get_json()["questions"]
    assert len(questions) > 0
    assert all(isinstance(q, str) for q in questions)


# ---------------------------------------------------------------------------
# Chat: create / list / message / dummy reply
# ---------------------------------------------------------------------------

def test_create_and_list_conversation(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    resp = client.get("/panda/conversations")
    assert resp.status_code == 200
    ids = [c["conversation_id"] for c in resp.get_json()["conversations"]]
    assert conversation_id in ids


def test_send_message_persists_and_falls_back_to_placeholder_for_unrecognized_question(logged_in_client):
    """"How many students do I have?" matches none of panda/intents.py's
    keyword lists (student counts aren't one of Part 1's answerable
    intents yet), so it falls through to prompts.py's honest placeholder -
    unlike the revenue/occupancy/renewals questions below, which now get a
    real, data-backed answer."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    resp = client.post(
        f"/panda/conversations/{conversation_id}/messages",
        json={"message": "How many students do I have?"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["user_message"]["role"] == "user"
    assert data["user_message"]["content"] == "How many students do I have?"
    assert data["assistant_message"]["role"] == "assistant"
    assert "not connected to a real" in data["assistant_message"]["content"]

    thread = client.get(f"/panda/conversations/{conversation_id}/messages")
    assert thread.status_code == 200
    roles = [m["role"] for m in thread.get_json()["messages"]]
    assert roles == ["user", "assistant"]


# ---------------------------------------------------------------------------
# Chat: Part 1 ("Ask") real intent-based replies (ADR-47)
# ---------------------------------------------------------------------------

def _send(client, conversation_id, message):
    resp = client.post(
        f"/panda/conversations/{conversation_id}/messages",
        json={"message": message},
    )
    assert resp.status_code == 201
    return resp.get_json()["assistant_message"]["content"]


def test_revenue_question_answers_with_real_data_for_fresh_admin(logged_in_client):
    """A fresh admin has no income recorded either month - the reply must
    say so honestly rather than reporting a fabricated trend."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "What's my revenue trend this month?")
    assert "don't see any recorded income" in reply


def test_explain_revenue_question_answers_honestly_for_fresh_admin(logged_in_client):
    """A fresh admin has no income recorded either month - same honest
    "nothing to explain yet" the plain revenue reply gives, not a
    fabricated factor list."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "Why is my revenue decreasing?")
    assert "don't see any recorded income" in reply
    assert "nothing to explain" in reply


def test_explain_revenue_question_reports_new_admissions_factor(logged_in_client):
    """Part 3 (ADR-49): a real admission + payment made today (this
    calendar month) with no prior-month admissions gives previous_month
    income of 0 and current_month income > 0 - a genuine "up" trend with a
    real, verifiable admissions-growth factor behind it, not a guess."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    today = datetime.date.today()
    join_date = today.isoformat()
    end_date = (today + datetime.timedelta(days=30)).isoformat()

    make_enquiry(client)
    enquiry_id = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, enquiry_id, join_date=join_date)
    student_id = get_last_student_id(admin["admin_id"])
    create_membership(client, student_id, joining_date=join_date, end_date=end_date)

    reply = _send(client, conversation_id, "Why is my revenue up this month?")
    assert "up 100.0%" in reply
    assert "New admissions grew from 0 last month to 1 this month." in reply


def test_occupancy_question_answers_with_real_shift_data(logged_in_client):
    """A fresh admin has default seating capacity but zero occupied seats -
    the reply should list real shift figures, not a placeholder."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "How's my seat occupancy?")
    assert "occupancy by shift" in reply
    assert "Morning" in reply
    assert "%" in reply


def test_renewals_question_answers_with_real_data_for_fresh_admin(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "Any memberships expiring soon?")
    assert "No memberships are expired or expiring" in reply


def test_deletion_request_is_declined_not_actioned(logged_in_client):
    """Matches the original spec's Scenario A - Panda must never claim to
    delete anything, only redirect to the app's own controls."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "Delete Rahul Sharma")
    assert "can't make that change directly" in reply


def test_pricing_change_request_is_declined_not_actioned(logged_in_client):
    """Matches the original spec's Scenario B."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "Increase all membership fees")
    assert "can't make that change directly" in reply


def test_risk_students_question_answers_with_real_data_for_fresh_admin(logged_in_client):
    """As of Part 2 (ADR-48), Panda computes real risk scores by reusing
    AI Center's own compute_student_risk() - a fresh admin has no students,
    so the honest answer is "no High risk students", not a redirect."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "Which students are likely to leave?")
    assert "No students are currently flagged High risk" in reply
    assert "AI Center" in reply


def test_retention_question_answers_with_real_data_for_fresh_admin(logged_in_client):
    """Topic expansion (ADR-52), not a sixth part of the progression: a
    fresh admin has no membership history at all - the honest "nothing to
    measure retention against" reply, not a fabricated ratio."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "How can I retain students?")
    assert "No membership history yet" in reply


def test_retention_question_reports_real_retention_and_risk_data(logged_in_client):
    """A real, currently-active membership must surface as a real
    retention ratio, not the fresh-admin placeholder."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    make_enquiry(client)
    enquiry_id = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, enquiry_id)
    student_id = get_last_student_id(admin["admin_id"])
    create_membership(client, student_id, paid_amount="500", due_amount="0")

    reply = _send(client, conversation_id, "How can I retain students?")
    assert "100.0% of your memberships are currently active (1 of 1)" in reply


def test_admissions_question_answers_with_real_data_for_fresh_admin(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "How many admissions this month?")
    assert "No admissions recorded yet" in reply


def test_purpose_performance_question_answers_with_real_data_for_fresh_admin(logged_in_client):
    """A fresh admin has no students, so there's no purpose data - the
    reply must say so honestly rather than naming a fabricated category."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "Best performing course?")
    assert "No student purpose data yet" in reply


def test_batch_question_uses_purpose_data_not_recommend_fallback(logged_in_client):
    """Regression guard at the HTTP layer for the "should i" keyword
    collision - a batch question must reach the real purpose-performance
    reply, not the generic "can't generate recommendations yet" one."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "Which batch should I promote?")
    assert "Here's what I'd focus on" not in reply
    assert "No student purpose data yet" in reply


def test_forecast_question_reports_no_history_for_fresh_admin(logged_in_client):
    """Part 5 (ADR-51): a fresh admin has no real monthly history in any of
    the three forecast areas - the honest "not enough history" reply, not
    a fabricated ₹0/0% projection."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "What is expected next month?")
    assert "don't have enough months of real history" in reply


def _renew_membership(client, student_id, **overrides):
    data = {
        "plan_name": "Custom",
        "joining_date": "2026-07-22",
        "duration_days": "30",
        "end_date": "2026-08-21",
        "remarks": "auto-created by QA suite",
        "payment_mode": "Cash",
        "paid_amount": "500",
        "total_fee": "500",
    }
    data.update(overrides)
    return client.post(f"/memberships/renew/{student_id}", data=data, follow_redirects=True)


def _admit_with_membership(client, admin_id, join_date, end_date):
    """Admits a new student and gives them one membership spanning
    [join_date, end_date] - returns the new student_id."""
    make_enquiry(client)
    enquiry_id = get_last_enquiry_id(admin_id)
    admit_student(client, enquiry_id, join_date=join_date)
    student_id = get_last_student_id(admin_id)
    create_membership(
        client, student_id,
        joining_date=join_date, end_date=end_date,
        paid_amount="500", due_amount="0",
    )
    return student_id


def test_forecast_question_reports_real_occupancy_and_churn_trend_from_seeded_history(logged_in_client):
    """Part 5 (ADR-51): seeds real, backdated membership history (via the
    normal admission/membership/renewal routes - joining_date/end_date are
    accepted as-is, unlike Cashbook entry_date which the app always stamps
    with today's real date, see the revenue-forecast test below) spanning
    several real calendar months, then verifies the forecast reply reflects
    genuine computed trends, not placeholders.

    Dates are derived from database.bi_queries.last_n_months(6) itself
    (the exact function panda/forecasting.py fits its trend over) rather
    than hardcoded literals, so this test stays correct regardless of what
    day it actually runs on:

    - Occupancy: 3 students admitted in the window's 1st, 3rd, and 5th
      months, each still active through the current month - a real, rising
      month-by-month occupancy count, so "trending up" is a verifiable
      fact, not an assumption.
    - Renewals/churn: 2 students whose first membership lapsed (no renewal
      recorded) and 2 whose first membership was genuinely renewed via
      /memberships/renew, interleaved across the window's 2nd-5th months -
      giving a real, exactly-computable lapse-rate sequence
      [1.0, 0.0, 1.0, 0.0] (the same "did this student renew" test
      database/ai_center_queries.py's _renewal_signal() already uses, see
      panda/forecasting.py's docstring) whose linear-fit projection is
      deterministically 0.0%, trending "down".
    - Revenue: this admin has no backdated Cashbook income (the app always
      dates an automatic Income entry with today's real date - see
      database/payment_queries.py's record_payment()), so revenue must
      still honestly report "not enough months" even though the other two
      have real data - proving the reply handles partial availability
      correctly, not all-or-nothing.
    """
    client, admin = logged_in_client
    admin_id = admin["admin_id"]

    from database.bi_queries import last_n_months
    m0, m1, m2, m3, m4, m5 = last_n_months(6)
    # Well past the 6-month window's last month (today), so these "still
    # ongoing" memberships never get counted as "expiring" inside the
    # churn window below - only D/E1/F/G1's actual lapse/renewal months
    # (m1-m4) should contribute a churn data point.
    still_active_end = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()

    # Occupancy: rising overlap count in months 0 -> 2 -> 4, all still
    # active through the current month (month 5).
    _admit_with_membership(client, admin_id, f"{m0}-01", still_active_end)
    _admit_with_membership(client, admin_id, f"{m2}-01", still_active_end)
    _admit_with_membership(client, admin_id, f"{m4}-01", still_active_end)

    # Churn: D lapses in month 1, E renews in month 2, F lapses in month 3,
    # G renews in month 4 - rates by month = [1.0, 0.0, 1.0, 0.0].
    _admit_with_membership(client, admin_id, f"{m0}-01", f"{m1}-15")

    student_e = _admit_with_membership(client, admin_id, f"{m0}-01", f"{m2}-10")
    _renew_membership(
        client, student_e,
        joining_date=f"{m2}-15", end_date=still_active_end, total_fee="500", paid_amount="500",
    )

    _admit_with_membership(client, admin_id, f"{m1}-01", f"{m3}-20")

    student_g = _admit_with_membership(client, admin_id, f"{m2}-01", f"{m4}-10")
    _renew_membership(
        client, student_g,
        joining_date=f"{m4}-12", end_date=still_active_end, total_fee="500", paid_amount="500",
    )

    from panda import insights

    occupancy = insights.get_seat_demand_forecast(admin_id)
    assert occupancy is not None
    assert occupancy["trend_direction"] == "up"
    assert occupancy["projected_occupancy_pct"] > 0

    churn = insights.get_churn_forecast(admin_id)
    assert churn is not None
    assert churn["months_used"] == 4
    assert churn["trend_direction"] == "down"
    assert churn["projected_churn_rate_pct"] == 0.0

    revenue = insights.get_revenue_forecast(admin_id)
    assert revenue is None

    conversation_id = _create_conversation(client)
    reply = _send(client, conversation_id, "What is expected next month?")
    assert "Occupancy: trending up" in reply
    assert "Renewals:" in reply and "0.0%" in reply
    assert "Revenue: not enough months of real income history yet" in reply


def test_forecast_revenue_projects_real_trend_from_backdated_cashbook_history(logged_in_client):
    """Part 5 (ADR-51): the app itself can never backdate a Cashbook
    Income entry (payment_date/entry_date are always stamped with today's
    real date - see database/payment_queries.py's record_payment()), so a
    genuine multi-month revenue history can't be produced by driving the
    UI/routes at all. Inserting the rows directly is the same precedented
    "the UI can't backdate this, so bypass it for test setup only" pattern
    tests/test_05_dashboard_bi_analytics.py's
    test_revenue_monthly_bucketing_differs_by_year already uses for
    payments - applied here to `cashbook` (what get_monthly_income() /
    forecast_revenue() actually read) instead of `payments`.

    A perfect ₹300/month arithmetic progression across all 6 window months
    (500, 800, ..., 2000) makes the projected next value exactly
    computable by hand (2300) - an exact assertion, not just a direction.
    """
    client, admin = logged_in_client
    admin_id = admin["admin_id"]

    from database.bi_queries import last_n_months
    from database.supabase_client import get_supabase_client
    supabase = get_supabase_client()

    months = last_n_months(6)

    next_id_row = (
        supabase.table("cashbook").select("entry_id").order("entry_id", desc=True).limit(1).execute()
    )
    next_entry_id = (next_id_row.data[0]["entry_id"] + 1) if next_id_row.data else 1

    for i, month in enumerate(months):
        amount = 500 + 300 * i
        supabase.table("cashbook").insert({
            "entry_id": next_entry_id + i,
            "admin_id": admin_id,
            "type": "Income",
            "category": "Admission Fee",
            "person": "QA Backdated Student",
            "description": "QA backdated seed for Part 5 forecast test",
            "amount": amount,
            "payment_method": "Cash",
            "entry_date": f"{month}-10",
            "reference_id": f"QA-FORECAST-{next_entry_id + i}",
            "source": "QA Backdated Seed",
        }).execute()

    from panda import insights

    revenue = insights.get_revenue_forecast(admin_id)
    assert revenue is not None
    assert revenue["trend_direction"] == "up"
    assert revenue["projected_amount"] == 2300.0
    assert revenue["months_used"] == 6


def test_recommend_question_answers_with_real_action_items_for_fresh_admin(logged_in_client):
    """Part 4 (ADR-50): a fresh admin has nothing flagged by any of
    get_action_items()'s checks, so its own honest "No urgent issues
    detected" filler item is what comes back - real data, not the old
    "can't generate recommendations yet" placeholder."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "How can I increase profit?")
    assert "can't generate recommendations yet" not in reply
    assert "No urgent issues detected" in reply
    assert "finances and memberships look stable" in reply


def test_recommend_question_reports_real_pending_fees_action_item(logged_in_client):
    """A real pending balance (from a Custom-plan membership left partially
    unpaid) must surface as one of get_action_items()'s actual line items,
    not a fabricated suggestion - verifies Part 4 threads through live data,
    not just the empty-roster filler case above."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    make_enquiry(client)
    enquiry_id = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, enquiry_id)
    student_id = get_last_student_id(admin["admin_id"])
    create_membership(client, student_id, paid_amount="200", due_amount="300")

    reply = _send(client, conversation_id, "What should I do today?")
    assert "₹300 in pending fees" in reply
    assert "Follow up with members carrying outstanding balances." in reply


def test_cash_question_answers_with_real_data_for_fresh_admin(logged_in_client):
    """A fresh admin has no cashbook activity and no memberships - the
    honest "no cash activity recorded" reply, not a fabricated number."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "How can I manage cash?")
    assert "No cash activity recorded yet" in reply


def test_cash_question_reports_real_pending_fees_and_expense_breakdown(logged_in_client):
    """A real pending balance (from a partially-unpaid Custom-plan
    membership) and a real manual Expense entry must surface as this
    admin's actual collection rate and expense breakdown, not a fabricated
    one - verifies the cash-management reply threads through live data,
    not just the empty-state case above."""
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
            "description": "QA cash test expense",
        },
        follow_redirects=True,
    )

    reply = _send(client, conversation_id, "How can I manage cash?")
    assert "₹200 collected of ₹500 billed" in reply
    assert "₹300 in fees is still pending collection." in reply
    assert "Rent: ₹1,000" in reply


def test_nav_help_question_answers_with_real_instructions(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "How do I add a new student?")
    assert "Students" in reply and "Admission" in reply


def test_greeting_is_answered_with_real_capability_list(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "Hello")
    assert "Hi, I'm Panda" in reply


def test_conversation_title_set_from_first_user_message(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    client.post(
        f"/panda/conversations/{conversation_id}/messages",
        json={"message": "What's my revenue trend?"},
    )

    resp = client.get("/panda/conversations")
    conversation = next(c for c in resp.get_json()["conversations"] if c["conversation_id"] == conversation_id)
    assert conversation["title"] == "What's my revenue trend?"


def test_empty_message_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = client.post("/panda/conversations/999999/messages", json={"message": "   "})
    assert resp.status_code == 400


def test_message_over_length_limit_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = client.post("/panda/conversations/999999/messages", json={"message": "x" * 2001})
    assert resp.status_code == 400


def test_message_to_nonexistent_conversation_returns_404_when_tables_exist(logged_in_client):
    client, admin = logged_in_client
    resp = client.post("/panda/conversations/999999/messages", json={"message": "hello"})
    if resp.status_code == 503:
        pytest.skip("panda_conversations/panda_messages tables not yet created on this Supabase project")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cross-tenant isolation (IDOR) - same category of check as
# tests/test_08_cross_tenant_isolation.py, applied to Panda's own chat data.
# ---------------------------------------------------------------------------

def test_admin_b_cannot_read_admin_a_conversation(app):
    client_a = app.test_client()
    client_b = app.test_client()
    _register_and_login(client_a, "iso_a")
    _register_and_login(client_b, "iso_b")

    conversation_id = _create_conversation(client_a)
    client_a.post(
        f"/panda/conversations/{conversation_id}/messages",
        json={"message": "Admin A's private question"},
    )

    resp = client_b.get(f"/panda/conversations/{conversation_id}/messages")
    assert resp.status_code == 404


def test_admin_b_cannot_post_into_admin_a_conversation(app):
    client_a = app.test_client()
    client_b = app.test_client()
    _register_and_login(client_a, "iso_c")
    _register_and_login(client_b, "iso_d")

    conversation_id = _create_conversation(client_a)

    resp = client_b.post(
        f"/panda/conversations/{conversation_id}/messages",
        json={"message": "Admin B trying to inject a message"},
    )
    assert resp.status_code == 404

    thread = client_a.get(f"/panda/conversations/{conversation_id}/messages")
    assert thread.get_json()["messages"] == []


def test_admin_b_conversation_list_excludes_admin_a(app):
    client_a = app.test_client()
    client_b = app.test_client()
    _register_and_login(client_a, "iso_e")
    _register_and_login(client_b, "iso_f")

    conversation_id = _create_conversation(client_a)

    resp = client_b.get("/panda/conversations")
    ids = [c["conversation_id"] for c in resp.get_json()["conversations"]]
    assert conversation_id not in ids
