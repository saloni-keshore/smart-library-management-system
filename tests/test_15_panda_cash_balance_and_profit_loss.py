"""Regression tests for the 2026-08-25 pre-pilot Panda audit's approved
implementation (ADR-55): two new topic-specific intents, INTENT_CASH_BALANCE
and INTENT_PROFIT_LOSS, closing the audit's two top-ranked gaps -
"How much cash do I have?" and "Tell me about my profit or loss?" - both of
which used to fall all the way through to the generic placeholder even
though the exact real data they need
(database/cashbook_queries.py's get_cash_balance()/get_total_income()/
get_total_expense()/get_monthly_profit()) already existed, already correct,
just never wired into Panda. No new calculation was written for either
intent - see panda/insights.py's get_cash_balance()/get_profit_loss_summary()
and panda/intents.py's _reply_cash_balance()/_reply_profit_loss().
"""
import pytest

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


def _add_cashbook_entry(client, transaction_type, category, amount, payment_method="Cash"):
    return client.post(
        "/cashbook/add",
        data={
            "transaction_type": transaction_type,
            "category": category,
            "amount": amount,
            "payment_method": payment_method,
            "person": "",
            "description": "QA cash-balance/profit-loss test entry",
        },
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Intent classification - natural-language variations
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "How much cash do I have?",
    "How much cash is on hand?",
    "What's my cash balance?",
    "What's in my cashbox?",
    "How much physical cash do I have?",
    "how much cash in hand do I have",
    "what is in my cash box",
])
def test_intent_cash_balance_variations_detected(text):
    assert intents.detect_intent(text) == intents.INTENT_CASH_BALANCE


@pytest.mark.parametrize("text", [
    "Tell me about my profit or loss",
    "Am I making a profit?",
    "Am I making a loss?",
    "What's my net profit?",
    "What's my net loss?",
    "How much profit did I make?",
    "How much did I lose?",
    "Is my business profitable?",
])
def test_intent_profit_loss_variations_detected(text):
    assert intents.detect_intent(text) == intents.INTENT_PROFIT_LOSS


# ---------------------------------------------------------------------------
# Required collision tests
# ---------------------------------------------------------------------------

def test_intent_increase_profit_stays_recommend_not_profit_loss():
    """"profit" is a bare _PROFIT_LOSS_PHRASES word, but _RECOMMEND_PHRASES
    ("increase profit"/"how can i increase") is checked first in
    detect_intent() specifically so this doesn't regress."""
    assert intents.detect_intent("How can I increase profit?") == intents.INTENT_RECOMMEND
    assert intents.detect_intent("How can I improve profit?") == intents.INTENT_RECOMMEND


def test_intent_profit_or_loss_question_is_profit_loss():
    assert intents.detect_intent("Tell me about my profit or loss") == intents.INTENT_PROFIT_LOSS


def test_intent_cash_balance_question_is_cash_balance():
    assert intents.detect_intent("How much cash do I have?") == intents.INTENT_CASH_BALANCE


def test_intent_manage_cash_stays_cash_management():
    """Existing INTENT_CASH (ADR-52) must be completely unaffected."""
    assert intents.detect_intent("How can I manage cash?") == intents.INTENT_CASH


@pytest.mark.parametrize("text", [
    "How much cash did I collect?",
    "How much cash have I collected?",
])
def test_intent_cash_collected_does_not_become_cash_balance(text):
    """A collection question is not a balance question - must not be
    misrouted just because both mention "cash". Falling through to unknown
    is acceptable (that gap already existed before this change); becoming
    INTENT_CASH_BALANCE would not be."""
    assert intents.detect_intent(text) != intents.INTENT_CASH_BALANCE


@pytest.mark.parametrize("text", [
    "forecast", "predict", "what's expected next month",
    "will occupancy increase?",
])
def test_intent_forecast_questions_remain_forecast(text):
    assert intents.detect_intent(text) == intents.INTENT_FORECAST


def test_intent_forecast_beats_profit_loss_wording():
    """A forecast-flavored question that also happens to contain "profit"
    must still resolve to forecast - _FORECAST_PHRASES is checked well
    before _PROFIT_LOSS_PHRASES in detect_intent()."""
    assert intents.detect_intent("Will I be profitable next month?") == intents.INTENT_FORECAST


# ---------------------------------------------------------------------------
# Empty-data behavior
# ---------------------------------------------------------------------------

def test_cash_balance_question_answers_zero_for_fresh_admin(logged_in_client):
    """A fresh admin has no cashbook rows at all - get_cash_balance()
    correctly returns 0, and 0 is itself the honest, correct answer (not a
    fabricated placeholder number)."""
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "How much cash do I have?")
    assert "₹0" in reply
    assert "cash-payment-method" in reply


def test_profit_loss_question_answers_honestly_for_fresh_admin(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    reply = _send(client, conversation_id, "Tell me about my profit or loss")
    assert "No income or expenses recorded yet" in reply


# ---------------------------------------------------------------------------
# Real-data correctness + the cash-balance-vs-profit distinction
# ---------------------------------------------------------------------------

def test_cash_balance_reply_matches_real_cashbook_query(logged_in_client):
    """A real Cash-method income entry and a real Cash-method expense entry
    must surface as the exact same number
    database/cashbook_queries.get_cash_balance() computes - verified
    directly against that query, not just presence of a string."""
    from database.cashbook_queries import get_cash_balance

    client, admin = logged_in_client
    admin_id = admin["admin_id"]
    conversation_id = _create_conversation(client)

    _add_cashbook_entry(client, "Income", "Donation", "5000", payment_method="Cash")
    _add_cashbook_entry(client, "Expense", "Rent", "1200", payment_method="Cash")
    # Non-cash entry must not affect the cash-balance figure.
    _add_cashbook_entry(client, "Income", "Donation", "9000", payment_method="UPI")

    reply = _send(client, conversation_id, "What's my cash balance?")
    real_balance = get_cash_balance(admin_id)

    assert real_balance == 3800
    assert f"₹{real_balance:,.0f}" in reply
    assert "₹9,000" not in reply


def test_profit_loss_reply_matches_real_cashbook_totals(logged_in_client):
    """Verified directly against database/cashbook_queries.py's
    get_total_income()/get_total_expense() - the all-time net must be
    byte-identical to a plain income-minus-expense of those two real
    numbers, and must explicitly say "every payment method", distinguishing
    it from cash balance."""
    from database.cashbook_queries import get_total_expense, get_total_income

    client, admin = logged_in_client
    admin_id = admin["admin_id"]
    conversation_id = _create_conversation(client)

    _add_cashbook_entry(client, "Income", "Donation", "5000", payment_method="Cash")
    _add_cashbook_entry(client, "Income", "Donation", "9000", payment_method="UPI")
    _add_cashbook_entry(client, "Expense", "Rent", "20000", payment_method="Cash")

    reply = _send(client, conversation_id, "Tell me about my profit or loss")

    total_income = get_total_income(admin_id)
    total_expense = get_total_expense(admin_id)
    net = total_income - total_expense

    assert total_income == 14000
    assert total_expense == 20000
    assert net == -6000
    assert f"₹{total_income:,.0f} income" in reply
    assert f"₹{total_expense:,.0f} expense" in reply
    assert f"net loss of ₹{abs(net):,.0f}" in reply
    assert "every payment method" in reply


def test_cash_balance_and_profit_loss_can_legitimately_disagree_in_sign(logged_in_client):
    """The scenario the audit specifically flagged: positive cash balance,
    negative overall profit, because cash balance is Cash-method-only while
    profit/loss spans every payment method. Both replies must independently
    report the correct sign for their own definition - neither must borrow
    the other's number."""
    from database.cashbook_queries import get_cash_balance, get_total_expense, get_total_income

    client, admin = logged_in_client
    admin_id = admin["admin_id"]
    conversation_id = _create_conversation(client)

    # Cash: +10000 income, no cash expense -> cash balance positive.
    _add_cashbook_entry(client, "Income", "Donation", "10000", payment_method="Cash")
    # UPI: a big expense with no matching income -> overall net turns negative.
    _add_cashbook_entry(client, "Expense", "Furniture", "25000", payment_method="UPI")

    cash_balance = get_cash_balance(admin_id)
    net = get_total_income(admin_id) - get_total_expense(admin_id)
    assert cash_balance > 0
    assert net < 0

    cash_reply = _send(client, conversation_id, "How much cash do I have?")
    profit_reply = _send(client, conversation_id, "Tell me about my profit or loss")

    assert f"₹{cash_balance:,.0f}" in cash_reply
    assert f"net loss of ₹{abs(net):,.0f}" in profit_reply


def test_profit_loss_reply_marks_current_month_as_partial(logged_in_client, monkeypatch):
    """A monthly question must never present the current, still-in-progress
    month as a finished total. Direct unit test against
    panda/intents.py._reply_profit_loss(), monkeypatching
    panda/insights.py's wrapper - deterministic, avoids depending on real
    calendar timing across a multi-month history."""
    from panda import insights

    monkeypatch.setattr(insights, "get_profit_loss_summary", lambda admin_id: {
        "total_income": 10000,
        "total_expense": 6000,
        "net_profit": 4000,
        "monthly": {"2026-05": 800, "2026-06": 1000, "2026-07": -2000, "2026-08": 500},
        "current_month": "2026-08",
    })

    reply = intents._reply_profit_loss(admin_id=1)
    assert "2026-08: ₹500 profit (this month is still in progress)" in reply
    assert "2026-07: ₹2,000 loss" in reply
    assert "2026-06: ₹1,000 profit" in reply
    assert "2026-05" not in reply  # only the most recent 3 months are shown


# ---------------------------------------------------------------------------
# Deterministic output
# ---------------------------------------------------------------------------

def test_cash_balance_reply_is_identical_across_repeated_calls(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    _add_cashbook_entry(client, "Income", "Donation", "2000", payment_method="Cash")

    first = _send(client, conversation_id, "How much cash do I have?")
    second = _send(client, conversation_id, "How much cash do I have?")
    assert first == second


def test_profit_loss_reply_is_identical_across_repeated_calls(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    _add_cashbook_entry(client, "Income", "Donation", "2000", payment_method="Cash")
    _add_cashbook_entry(client, "Expense", "Rent", "500", payment_method="Cash")

    first = _send(client, conversation_id, "Tell me about my profit or loss")
    second = _send(client, conversation_id, "Tell me about my profit or loss")
    assert first == second


# ---------------------------------------------------------------------------
# Data isolation - admin-scoped, no cross-tenant leakage
# ---------------------------------------------------------------------------

def _register_and_login(client, suffix):
    import random
    import string

    from tests.conftest import get_admin_by_username

    creds = {
        "full_name": f"Panda CashProfit {suffix}",
        "username": f"qa_panda_cp_{suffix}",
        "mobile": "9" + "".join(random.choices(string.digits, k=9)),
        "email": f"panda_cp_{suffix}@example.com",
        "password": "PandaPass1",
        "confirm_password": "PandaPass1",
    }
    client.post("/register", data=creds, follow_redirects=True)
    client.post("/", data={"username": creds["username"], "password": creds["password"]}, follow_redirects=True)
    creds["admin_id"] = get_admin_by_username(creds["username"])["admin_id"]
    return creds


def test_cash_balance_reply_does_not_leak_between_admins(app):
    """Admin A has a real cash balance; Admin B (fresh) must get the clean
    ₹0 reply, never Admin A's figure."""
    import random
    import string

    client_a = app.test_client()
    client_b = app.test_client()
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    _register_and_login(client_a, f"cashbal_a_{suffix}")
    _register_and_login(client_b, f"cashbal_b_{suffix}")

    _add_cashbook_entry(client_a, "Income", "Donation", "7777", payment_method="Cash")

    conv_a = client_a.post("/panda/conversations")
    if conv_a.status_code == 503:
        pytest.skip("panda_conversations/panda_messages tables not yet created on this Supabase project")
    conv_a_id = conv_a.get_json()["conversation"]["conversation_id"]
    reply_a = client_a.post(
        f"/panda/conversations/{conv_a_id}/messages", json={"message": "How much cash do I have?"}
    ).get_json()["assistant_message"]["content"]
    assert "₹7,777" in reply_a

    conv_b_id = client_b.post("/panda/conversations").get_json()["conversation"]["conversation_id"]
    reply_b = client_b.post(
        f"/panda/conversations/{conv_b_id}/messages", json={"message": "How much cash do I have?"}
    ).get_json()["assistant_message"]["content"]
    assert "₹7,777" not in reply_b
    assert "₹0" in reply_b


def test_profit_loss_reply_does_not_leak_between_admins(app):
    """Admin A has real income/expense; Admin B (fresh) must get the clean
    "no income or expenses recorded yet" reply, never Admin A's figures."""
    import random
    import string

    client_a = app.test_client()
    client_b = app.test_client()
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    _register_and_login(client_a, f"pl_a_{suffix}")
    _register_and_login(client_b, f"pl_b_{suffix}")

    _add_cashbook_entry(client_a, "Income", "Donation", "6666", payment_method="Cash")
    _add_cashbook_entry(client_a, "Expense", "Rent", "1111", payment_method="Cash")

    conv_a = client_a.post("/panda/conversations")
    if conv_a.status_code == 503:
        pytest.skip("panda_conversations/panda_messages tables not yet created on this Supabase project")
    conv_a_id = conv_a.get_json()["conversation"]["conversation_id"]
    reply_a = client_a.post(
        f"/panda/conversations/{conv_a_id}/messages", json={"message": "Tell me about my profit or loss"}
    ).get_json()["assistant_message"]["content"]
    assert "₹6,666" in reply_a

    conv_b_id = client_b.post("/panda/conversations").get_json()["conversation"]["conversation_id"]
    reply_b = client_b.post(
        f"/panda/conversations/{conv_b_id}/messages", json={"message": "Tell me about my profit or loss"}
    ).get_json()["assistant_message"]["content"]
    assert "₹6,666" not in reply_b
    assert "No income or expenses recorded yet" in reply_b
