"""Rule/keyword-based intent classification for Panda's chat replies.

Part 1 ("Ask"), Part 2 ("Analyze"), Part 3 ("Explain"), Part 4
("Recommend"), and Part 5 ("Forecast") of the
Ask -> Analyze -> Explain -> Recommend -> Forecast capability progression
(see PANDA_SPEC.md, ADR-47/ADR-48/ADR-49/ADR-50/ADR-51) - the whole
progression is now real. No external AI API and no machine learning model -
every intent below is a literal keyword match against a
punctuation-stripped, word-bounded copy of the message text, and every
answerable intent's reply is composed from panda/insights.py's existing
read-only data.

A genuinely unrecognized question falls through to
prompts.generate_placeholder_reply(). Student risk (Part 2, as of ADR-48)
now answers for real instead of redirecting - see _reply_risk_students().
"Which batch should I promote?" has no real batch data anywhere in this
schema, so it's answered with the closest real data (purpose category
performance) with an explicit disclaimer, not silently treated as the same
question - see _reply_purpose_performance(). A "why is revenue X" question
(Part 3, ADR-49) gets its own real, ranked-factor reply - see
_reply_explain_revenue() - distinct from the plain revenue-trend reply,
which never speculates about a cause. A recommend question ("how can I
increase profit?", "what should I do?" - Part 4, ADR-50) returns this
admin's real, ranked action items, reusing Business Intelligence's existing
Action Center verbatim - see _reply_recommend(). A forecast question
("what's expected next month?" - Part 5, ADR-51) returns a real, simple
linear trend projection over this admin's own revenue/occupancy/renewal
history (panda/forecasting.py), never a fabricated number - see
_reply_forecast() for how it handles not having enough real history yet.

Two more topic-specific intents, INTENT_RETENTION and INTENT_CASH (added
2026-08-20, ADR-52), extend Part 1's keyword coverage laterally to
student-retention questions ("how can I retain students?", "how do I
reduce churn?") and cash-management questions ("how can I manage cash?",
"where is my cash going?") - not a sixth part of the Ask->Analyze->
Explain->Recommend->Forecast progression, which stays closed (see PF-8 in
docs/11_FUTURE_WORK.md). Each composes 2-4 of panda/insights.py's existing
wrappers into one topic-focused reply, the same composition shape
_reply_forecast()/_reply_explain_revenue() already use - no new business
logic, no LLM, no fabricated numbers. Retention's reply deliberately does
not attempt a cross-student "why are students at risk" aggregate (out of
scope - see ADR-52); it inherits get_top_risk_students()'s existing
100-student scoring cap (TD-60) and says so honestly when that cap is
actually hit.

2026-08-24 coverage pass (post-audit): a third topic-specific intent,
INTENT_EXPENSES, closes the audit's top-ranked gap - a direct expense
question ("how much are my expenses?", "what are my biggest expenses?")
used to fall all the way through to the generic placeholder even though
the exact data it needs (get_expense_breakdown()/get_expense_health()) was
already being read for the cash-management reply - see
_reply_expenses(). Same day: _reply_admissions() was broadened to also
report this admin's total roster size and best admission month (still one
query, get_admissions_trend()'s dict already had every month in it - see
that function), closing the "how many students do I have?"/"which month
had the most admissions?" gaps; _RENEWAL_PHRASES gained "expires" (the
present-tense-singular form "expire"/"expiring"/"expired" didn't cover);
_RISK_PHRASES gained "need attention"; and a forward-looking occupancy
question ("will occupancy increase?") now reaches _reply_forecast()
instead of the present-state occupancy reply - see
_is_future_occupancy_request(). None of these needed a new query or
changed any existing reply's data source, only wider keyword coverage and,
for admissions, reading more of a dict Part 2 was already fetching in
full.

2026-08-25 wording fix (final pre-pilot audit): _reply_admissions()'s
roster-count line said "You have N student(s) on your roster in total"
with no scope qualifier, even though get_student_count() counts every
student this admin has ever admitted (get_admin_students() has no status
filter) - a library with any real turnover has this number diverge from
"currently enrolled," which is what a non-technical owner asking "how many
students do I have?" most naturally means. Now says "...in total (all-time,
including students with lapsed memberships)." No calculation changed -
get_student_count() is untouched - only the sentence around it.

2026-08-25 cash balance / profit-loss coverage pass (ADR-55): closes the
two top-ranked gaps from a live read-only audit against a real admin
account ("sona", 17 real students) - "How much cash do I have?" and "Tell
me about my profit or loss?" both fell all the way through to the generic
placeholder before this, even though the exact real data both need
(database/cashbook_queries.py's get_cash_balance()/get_total_income()/
get_total_expense()/get_monthly_profit()) already existed and was already
correct, just never wired into Panda. INTENT_CASH_BALANCE
(_reply_cash_balance()) answers with a single defined number - cash-
payment-method income minus cash-payment-method expense, all-time -
deliberately never called "bank balance"/"total money available"/"total
collections", none of which this number actually represents.
INTENT_PROFIT_LOSS (_reply_profit_loss()) answers with an explicit
all-time net (income minus expense, every payment method) plus a recent-
months breakdown that marks the current month as still in progress rather
than presenting a partial month as a finished total. Neither intent is a
new calculation - both are thin panda/insights.py wrappers around
functions Cashbook's own reports already trusted. The two are kept
strictly separate, in both keyword coverage and reply text: a real library
can have a positive cash balance and a negative overall profit
simultaneously (Cash-only transactions vs. every payment method), and each
reply says so explicitly rather than letting an owner conflate the two.
"""

import re

from panda import insights, prompts

INTENT_ACTION_REQUEST = "action_request"
INTENT_EXPLAIN_REVENUE = "explain_revenue"
INTENT_REVENUE = "revenue"
INTENT_OCCUPANCY = "occupancy"
INTENT_RENEWALS = "renewals"
INTENT_ADMISSIONS = "admissions"
INTENT_PURPOSE_PERFORMANCE = "purpose_performance"
INTENT_RISK_STUDENTS = "risk_students"
INTENT_RETENTION = "retention"
INTENT_FORECAST = "forecast"
INTENT_RECOMMEND = "recommend"
INTENT_CASH = "cash_management"
INTENT_CASH_BALANCE = "cash_balance"
INTENT_PROFIT_LOSS = "profit_loss"
INTENT_EXPENSES = "expenses"
INTENT_NAV_HELP = "nav_help"
INTENT_GREETING = "greeting"
INTENT_UNKNOWN = "unknown"

_NON_WORD_RE = re.compile(r"[^a-z0-9]+")

_DELETE_VERBS = ("delete", "remove", "cancel", "terminate")
_PRICING_VERBS = ("increase", "decrease", "raise", "lower", "change", "update", "modify", "set")
_PRICING_NOUNS = ("fee", "fees", "price", "prices", "pricing", "rate", "rates")

# "need attention"/"needs attention" added 2026-08-24 (audit finding:
# "which students need attention" is a real synonym for "who is at risk",
# but shared no keyword with the rest of this list).
_RISK_PHRASES = (
    "risk", "leave", "leaving", "churn", "dropout", "drop out",
    "need attention", "needs attention",
)
_FORECAST_PHRASES = (
    "forecast", "predict", "prediction", "projection", "next month", "next week",
    "expected", "coming month", "upcoming month", "next 30 days", "outlook",
)
# Forward-looking occupancy questions ("will occupancy increase?") added
# 2026-08-24 (audit finding: this matched _OCCUPANCY_PHRASES's bare
# "occupancy" - checked much later - and never reached forecast, so a
# genuinely forward-looking question got a present-state occupancy reply
# instead). Deliberately scoped to occupancy vocabulary specifically, not a
# blanket "will X increase/decrease" pattern - forecast is checked this
# early (2nd) precisely so action-request wording keeps priority, but a
# generic "will"+direction-word combination here would also grab unrelated
# topics checked later in this same function (e.g. "how will retention
# improve" already matches retention's own unambiguous bare "retention"
# keyword and must keep winning there, not get short-circuited into
# forecast by a generic "will"+"improve" match with no occupancy word in
# it). See _is_future_occupancy_request() below.
_FUTURE_MARKERS = ("will",)
_FUTURE_DIRECTION_WORDS = (
    "increase", "decrease", "grow", "improve", "decline", "drop", "rise",
    "fall", "go up", "go down",
)
_RECOMMEND_PHRASES = (
    "recommend", "suggest", "suggestion", "how can i increase", "how do i increase",
    "how to increase", "should i", "what should i do", "improve profit",
    "grow revenue", "increase profit", "increase revenue",
)
# "why"/"reason"/"explain" combined with a revenue word - same "verb +
# noun" combination shape as _is_action_request() below, not a long list of
# literal "why is revenue ..." phrasings, so unlisted wordings ("what's the
# reason my income dropped", "can you explain my revenue") still classify
# correctly without needing their own entry (see ADR-49).
_WHY_PHRASES = ("why", "why's", "reason", "explain")
_REVENUE_PHRASES = ("revenue", "income", "earning", "earnings")
_OCCUPANCY_PHRASES = (
    "occupancy", "occupied", "seat", "seats", "capacity",
    "utilization", "utilisation", "shift", "shifts",
)
# "expires" added 2026-08-24 (2026-08-24 audit finding: "expire"/"expiring"/
# "expired" don't cover the present-tense-singular form, so "who expires
# today"/"who expires this week" fell through to the unknown placeholder
# even though "who is expiring soon" already worked).
_RENEWAL_PHRASES = ("renewal", "renewals", "renew", "expiring", "expires", "expire", "expired")
# Specific multi-word phrases only - a bare "admission"/"admissions" would
# also match a locality-flavored question like "which locality gives me the
# highest admissions", which has no real answer (no locality data exists,
# see PANDA_SPEC.md) and must keep falling through to the unknown fallback,
# not get a real-but-wrong (locality-less) admissions-trend answer instead.
# The roster-count and best-month/direction phrasings below were added
# 2026-08-24 (audit finding) - deliberately still literal phrases, not a
# bare "how many students" (that would collide with "how many students are
# expiring this week", a renewals question, since admissions is checked
# before renewals below).
_ADMISSIONS_PHRASES = (
    "admissions trend", "admission trend", "how many admissions",
    "new admissions", "admission count", "admissions this month",
    "admissions this year", "monthly admissions",
    "how many students do i have", "how many active students",
    "how many total students", "how many students in total",
    "which month had the most admissions", "best admission month",
    "are admissions increasing", "is admissions increasing",
    "admissions increasing", "admissions decreasing", "admissions growing",
)
# Expenses (added 2026-08-24, closing the audit's top-ranked coverage gap):
# "expense"/"expenses"/"expenditure" mean nothing else in this app's domain
# (same "unambiguous alone" treatment _RETENTION_PHRASES gives
# "retain"/"retention" below), so a bare mention is enough - generalizes to
# phrasings never spelled out here ("expense report", "monthly expenses",
# "biggest expense category"...), not just the ones the audit listed.
# "spend"/"spent"/"spending" cover phrasings with no "expense" root at all
# ("how much did I spend?"). "money going" is a literal two-word phrase,
# same shape as _CASH_PHRASES's "cash going" below - "where is my money
# going" has no expense/spend root either. "reduce expenses" is safe
# regardless of check order relative to retention: _RETENTION_VERBS
# includes "reduce", but "expenses" isn't in _RETENTION_NOUNS, so
# _is_retention_request() only fires on an actual churn/leaving noun.
_EXPENSE_PHRASES = ("expense", "expenses", "expenditure", "spend", "spent", "spending", "money going")
_PURPOSE_PHRASES = (
    "best course", "best performing course", "top course", "which course",
    "best purpose", "most popular purpose", "most popular course",
    "which batch", "best batch", "top batch",
)
_NAV_HELP_PHRASES = ("add a new student", "add new student", "add student", "new student", "admission process")
_GREETING_PHRASES = ("hello", "hi", "hey", "help", "what can you do", "what do you do")

# Retention (ADR-52): unambiguous alone ("retain"/"retention" mean nothing
# else in this app's domain), plus a verb+noun combination (same shape as
# _is_action_request()/_is_explain_revenue_request() below) for phrasings
# where the verb alone is too generic to trust ("reduce"/"stop" without a
# churn/leaving/dropout noun could just as easily be about expenses or
# anything else) - see ADR-52 for why this is checked before
# _RISK_PHRASES, which already contains the bare word "churn"/"leaving".
_RETENTION_PHRASES = ("retain", "retention", "keep students", "keep them longer")
_RETENTION_VERBS = ("reduce", "stop", "prevent", "lower")
_RETENTION_NOUNS = ("churn", "leaving", "dropout", "drop out")

# Cash management (ADR-52): a flat phrase list, not a verb+noun combination
# - unlike retention's generic verbs, "cash"/"collection"/"pending fees"
# don't otherwise appear in this app's vocabulary, and several real
# phrasings ("how is my cash flow", "where is my cash going") have no
# action verb at all.
_CASH_PHRASES = (
    "cash flow", "manage cash", "cash management", "cash collection",
    "collect cash", "collect fees", "collecting fees", "pending fees",
    "cash going", "where is my cash", "improve collection", "improve cash",
)

# Cash balance (added 2026-08-25, pre-pilot audit, ADR-55): distinct from
# cash MANAGEMENT above ("how can I manage cash", "where is my cash going")
# - this is "how much cash do I physically have right now", a single
# number (database/cashbook_queries.get_cash_balance()), not a
# collection-rate/expense-breakdown topic reply. "cashbox"/"cash box" are
# unambiguous alone (same "unambiguous alone" treatment _EXPENSE_PHRASES
# gives "expense"/"expenses" - this app has no other meaning for either).
# Every other real phrasing ("how much cash do I have", "what's my cash
# balance", "how much physical cash do I have") needs BOTH the word "cash"
# AND one of _CASH_BALANCE_MARKERS present - a flat phrase list would miss
# reasonable rewordings the required variations didn't spell out, but a
# bare "cash" match alone would wrongly catch "how much cash did I
# collect?" (a collection question, not a balance question - deliberately
# left unmatched here, see _is_cash_balance_request()'s own docstring).
# "do i have" (not bare "have") is deliberate: bare "have" would also match
# a rewording like "how much cash have I collected", which is a collection
# question, not a balance one; "do i have" doesn't appear in that ordering.
_CASH_BALANCE_STANDALONE_PHRASES = ("cashbox", "cash box")
_CASH_BALANCE_MARKERS = ("balance", "on hand", "in hand", "physical", "do i have", "drawer")

# Profit/loss (added 2026-08-25, pre-pilot audit, ADR-55): bare words,
# unambiguous alone in this app's domain (same treatment
# _RETENTION_PHRASES/_EXPENSE_PHRASES already give "retain"/"expense") -
# "profit"/"loss" mean nothing else here. Checked AFTER _RECOMMEND_PHRASES
# in detect_intent() specifically so "how can I increase profit?"/"improve
# profit" (already in _RECOMMEND_PHRASES) keep resolving to Recommend, not
# this - see detect_intent()'s docstring.
_PROFIT_LOSS_PHRASES = ("profit", "profitable", "loss", "lose", "lost", "losing")


def _normalize(text):
    """Lowercase, collapse every run of non-alphanumeric characters to a
    single space, and pad with a leading/trailing space - lets every
    keyword check below match whole words/phrases only (so e.g. "hi" never
    matches inside "which"), regardless of punctuation in the original
    message."""

    return " " + _NON_WORD_RE.sub(" ", text.lower()) + " "


def _contains_any(normalized, phrases):
    return any(f" {phrase} " in normalized for phrase in phrases)


def _is_action_request(normalized):
    has_delete = _contains_any(normalized, _DELETE_VERBS)
    has_pricing_change = (
        _contains_any(normalized, _PRICING_VERBS)
        and _contains_any(normalized, _PRICING_NOUNS)
    )
    return has_delete or has_pricing_change


def _is_explain_revenue_request(normalized):
    return _contains_any(normalized, _WHY_PHRASES) and _contains_any(normalized, _REVENUE_PHRASES)


def _is_retention_request(normalized):
    return _contains_any(normalized, _RETENTION_PHRASES) or (
        _contains_any(normalized, _RETENTION_VERBS) and _contains_any(normalized, _RETENTION_NOUNS)
    )


def _is_cash_balance_request(normalized):
    """"cashbox"/"cash box" are unambiguous alone; every other real
    phrasing needs the word "cash" AND a balance-flavored marker
    (_CASH_BALANCE_MARKERS) both present - see _CASH_BALANCE_MARKERS'
    comment for why a bare "cash" match alone isn't used (it would also
    catch "how much cash did I collect?", a collection question)."""

    return _contains_any(normalized, _CASH_BALANCE_STANDALONE_PHRASES) or (
        _contains_any(normalized, ("cash",)) and _contains_any(normalized, _CASH_BALANCE_MARKERS)
    )


def _is_future_occupancy_request(normalized):
    return (
        _contains_any(normalized, _FUTURE_MARKERS)
        and _contains_any(normalized, _FUTURE_DIRECTION_WORDS)
        and _contains_any(normalized, _OCCUPANCY_PHRASES)
    )


def detect_intent(text):
    """Ordered keyword matching - first match wins. Action requests are
    checked first since misclassifying one as an answerable question would
    be a security-relevant mistake (see the Panda ADRs in
    docs/DECISIONS.md on the read-only boundary), not just a quality one.
    Forecast is checked next, before retention/risk - "churn" is one of
    _RISK_PHRASES (a per-student risk-list keyword since Part 2), but a
    message combining it with real forecast wording ("predict churn next
    month") is asking for Part 5's aggregate trend projection, the more
    specific real answer, not Part 2's per-student list; a plain "which
    students are at risk of churning" with no forecast wording still
    correctly falls through to risk (no _FORECAST_PHRASES entry matches
    it). Retention (ADR-52) is checked next, before risk, for the same
    keyword-collision reason as forecast-vs-risk: "how do I reduce churn?"
    contains the bare word "churn" (a _RISK_PHRASES keyword), so checking
    retention first means it correctly reaches the retention-topic reply
    (the more specific answer to what was actually asked) instead of Part
    2's per-student risk list; a plain "which students are at risk of
    leaving" (no retention-flavored verb) still falls through to risk
    unchanged. Admissions/purpose-performance are checked before cash and
    recommend since a phrase like "which batch should I promote?" also
    contains "should i" (a recommend keyword) - the more specific,
    answerable intent must win. Cash management (ADR-52) is checked before
    recommend for the same specificity reason, though no actual keyword
    overlap with _RECOMMEND_PHRASES was found. Expenses (added 2026-08-24)
    is checked right after cash, before recommend, for the same specificity
    reason - no actual keyword overlap with cash or recommend was found
    either, since neither mentions "expense"/"spend"/"spending". Explain-
    revenue is checked after recommend, before the plain revenue check, so a
    genuinely recommend-flavored question that happens to also contain
    "why" (rare) still gets its own honest reply rather than being answered
    as if it asked for an explanation. A forward-looking occupancy question
    ("will occupancy increase?", added 2026-08-24) is checked alongside
    forecast, before retention/risk, for the same "more specific real
    answer must win" reason as the churn-vs-forecast case above. Cash
    balance (added 2026-08-25, ADR-55) is checked before cash management -
    "what's my cash balance"/"how much cash do I have" is a more specific,
    different question than "how can I manage cash", and no actual keyword
    overlap between the two was found (cash management's phrases are all
    verb-flavored - "manage"/"improve"/"collect" - none contain
    _CASH_BALANCE_MARKERS' words). Profit/loss (added 2026-08-25, ADR-55) is
    checked right after recommend, before explain-revenue - deliberately
    after recommend so "how can I increase profit?"/"improve profit"
    (_RECOMMEND_PHRASES) keep resolving to Recommend, since bare "profit" is
    also one of _PROFIT_LOSS_PHRASES and would otherwise shadow it."""

    normalized = _normalize(text)

    if _is_action_request(normalized):
        return INTENT_ACTION_REQUEST
    if _contains_any(normalized, _FORECAST_PHRASES) or _is_future_occupancy_request(normalized):
        return INTENT_FORECAST
    if _is_retention_request(normalized):
        return INTENT_RETENTION
    if _contains_any(normalized, _RISK_PHRASES):
        return INTENT_RISK_STUDENTS
    if _contains_any(normalized, _ADMISSIONS_PHRASES):
        return INTENT_ADMISSIONS
    if _contains_any(normalized, _PURPOSE_PHRASES):
        return INTENT_PURPOSE_PERFORMANCE
    if _is_cash_balance_request(normalized):
        return INTENT_CASH_BALANCE
    if _contains_any(normalized, _CASH_PHRASES):
        return INTENT_CASH
    if _contains_any(normalized, _EXPENSE_PHRASES):
        return INTENT_EXPENSES
    if _contains_any(normalized, _RECOMMEND_PHRASES):
        return INTENT_RECOMMEND
    if _contains_any(normalized, _PROFIT_LOSS_PHRASES):
        return INTENT_PROFIT_LOSS
    if _is_explain_revenue_request(normalized):
        return INTENT_EXPLAIN_REVENUE
    if _contains_any(normalized, _REVENUE_PHRASES):
        return INTENT_REVENUE
    if _contains_any(normalized, _OCCUPANCY_PHRASES):
        return INTENT_OCCUPANCY
    if _contains_any(normalized, _RENEWAL_PHRASES):
        return INTENT_RENEWALS
    if _contains_any(normalized, _NAV_HELP_PHRASES):
        return INTENT_NAV_HELP
    if _contains_any(normalized, _GREETING_PHRASES):
        return INTENT_GREETING
    return INTENT_UNKNOWN


def _reply_action_request(admin_id):
    return (
        "🐼 I can't make that change directly — deletions and pricing changes "
        "go through the app's own screens so they stay audited and reversible. "
        "I can still help you think through the likely impact using your real "
        "numbers if that's useful — just ask."
    )


def _growth_direction_text(growth):
    """"up X%"/"down X%"/"flat" - shared by _reply_revenue() and
    _reply_explain_revenue() so both describe the same growth_pct
    identically."""

    if growth > 0:
        return f"up {growth}%"
    if growth < 0:
        return f"down {abs(growth)}%"
    return "flat"


def _reply_revenue(admin_id):
    trend = insights.get_revenue_trend(admin_id)
    current, previous, growth = trend["current_month"], trend["previous_month"], trend["growth_pct"]

    if current == 0 and previous == 0:
        return "🐼 I don't see any recorded income yet this month or last month, so there's no trend to report yet."

    return (
        f"🐼 This month's income is {_growth_direction_text(growth)} compared to last month "
        f"(₹{current:,.0f} vs ₹{previous:,.0f})."
    )


def _reply_explain_revenue(admin_id):
    explanation = insights.get_revenue_explanation(admin_id)
    trend = explanation["trend"]
    current, previous, growth = trend["current_month"], trend["previous_month"], trend["growth_pct"]

    if current == 0 and previous == 0:
        return "🐼 I don't see any recorded income yet this month or last month, so there's nothing to explain yet."

    intro = (
        f"🐼 This month's income is {_growth_direction_text(growth)} compared to last month "
        f"(₹{current:,.0f} vs ₹{previous:,.0f})."
    )

    factors = explanation["factors"]
    if not factors:
        return (
            intro + " Nothing in the data I can check stands out as a clear factor for "
            "that yet — see Business Intelligence for a fuller breakdown."
        )

    lines = "\n".join(f"- {factor}" for factor in factors)
    return intro + " Here's what stands out in your data:\n" + lines


def _reply_occupancy(admin_id):
    summary = insights.get_shift_utilization(admin_id)
    shifts = summary["shifts"]

    if not shifts or all(shift["capacity"] == 0 for shift in shifts):
        return "🐼 No seating capacity is configured yet, so I can't report occupancy."

    lines = [
        f"- {shift['name']}: {shift['occupied']}/{shift['capacity']} seats ({shift['utilization_pct']}%)"
        for shift in shifts
    ]
    return "🐼 Here's your current seat occupancy by shift:\n" + "\n".join(lines)


def _reply_renewals(admin_id):
    counts = insights.get_expiring_memberships(admin_id)

    if counts["total"] == 0:
        return "🐼 No memberships are expired or expiring in the next 3 days."

    return (
        f"🐼 {counts['total']} membership(s) need attention: {counts['expired']} expired, "
        f"{counts['today']} expiring today, {counts['tomorrow']} expiring tomorrow, and "
        f"{counts['three_days']} expiring within 3 days."
    )


def _reply_risk_students(admin_id):
    top = insights.get_top_risk_students(admin_id)

    if not top:
        return (
            "🐼 No students are currently flagged High risk. You can see the full "
            "breakdown on AI Center → Student Risk Analysis."
        )

    lines = []
    for result in top:
        name = result["student"].get("full_name") or "A student"
        reason = result["reasons"][0]["reason"] if result["reasons"] else "multiple risk signals"
        lines.append(f"- {name} (risk score {result['score']}): {reason}")

    return (
        f"🐼 {len(top)} student(s) are currently High risk:\n" + "\n".join(lines) +
        "\nSee the full breakdown on AI Center → Student Risk Analysis."
    )


def _reply_retention(admin_id):
    """Retention-topic reply (ADR-52) - composes the retention ratio,
    churn trend, and top-risk-student list into one topic-focused message,
    the same "compose several existing wrappers, no new analysis logic"
    shape _reply_forecast() already uses. Deliberately does not attempt a
    cross-student "top reason" tally (out of scope - see ADR-52); reuses
    _reply_risk_students()'s own per-student reason formatting instead of
    duplicating it."""

    retention = insights.get_retention_summary(admin_id)

    if retention["total"] == 0:
        return (
            "🐼 No membership history yet, so there's nothing to measure retention "
            "against. Once you have real memberships, ask again and I'll show your "
            "actual renewal rate and at-risk students."
        )

    renewal_rate = round(retention["active"] / retention["total"] * 100, 1)
    lines = [
        f"- {renewal_rate}% of your memberships are currently active "
        f"({retention['active']} of {retention['total']})."
    ]

    churn = insights.get_churn_forecast(admin_id)
    if churn is not None:
        lines.append(
            f"- Renewal trend is {churn['trend_direction']}: of the "
            f"{churn['upcoming_expiring']} membership(s) expiring in the next 30 days, "
            f"roughly {churn['projected_lapses']} may not renew "
            f"(~{churn['projected_churn_rate_pct']}% recent lapse rate)."
        )
    else:
        lines.append("- Not enough real lapse history yet to project a churn trend.")

    top = insights.get_top_risk_students(admin_id)
    if top:
        coverage = insights.get_risk_scoring_coverage(admin_id)
        capped_note = (
            f" (scored the first {insights.MAX_STUDENTS_SCORED_FOR_CHAT} of "
            f"{coverage['total']} students)" if coverage["capped"] else ""
        )
        risk_lines = "\n".join(
            f"  - {result['student'].get('full_name') or 'A student'} "
            f"(risk score {result['score']}): "
            f"{result['reasons'][0]['reason'] if result['reasons'] else 'multiple risk signals'}"
            for result in top
        )
        lines.append(f"- {len(top)} student(s) are currently High risk{capped_note}:\n{risk_lines}")
    else:
        lines.append("- No students are currently flagged High risk.")

    return (
        "🐼 Here's your real retention picture:\n" + "\n".join(lines) +
        "\nConsider a renewal campaign if the active share looks low — see AI Center → "
        "Student Risk Analysis for full detail."
    )


def _reply_cash_balance(admin_id):
    """Cash-balance reply (added 2026-08-25, pre-pilot audit, ADR-55) - a
    single real number, insights.get_cash_balance() (itself a pure wrapper
    around database/cashbook_queries.py's get_cash_balance()), with an
    explicit definition attached so it's never mistaken for "total money
    available"/"bank balance"/"total collections" - it's Cash-payment-
    method transactions specifically, all-time. Deliberately never calls
    this "bank balance" or "total collections" - see this file's module
    docstring and panda/insights.py's for why cash balance and profit/loss
    (INTENT_PROFIT_LOSS, _reply_profit_loss() below) must stay two separate
    replies, never merged into one."""

    balance = insights.get_cash_balance(admin_id)
    amount_text = f"₹{balance:,.0f}" if balance >= 0 else f"-₹{abs(balance):,.0f}"

    return (
        f"🐼 Your current cash balance is {amount_text} — cash-payment-method "
        "income minus cash-payment-method expense, all-time. This is what's "
        "physically on hand (cash payments only, not UPI/Card/etc.), not the "
        "same thing as your overall profit or loss across all payment methods "
        "— ask me about profit/loss separately for that."
    )


def _reply_profit_loss(admin_id):
    """Profit/loss reply (added 2026-08-25, pre-pilot audit, ADR-55) -
    composes insights.get_profit_loss_summary() (itself a pure wrapper
    around database/cashbook_queries.py's get_total_income()/
    get_total_expense()/get_monthly_profit(), all already-computed real
    numbers) into an all-time figure plus a recent-months breakdown, always
    stating the period explicitly (never a bare, unscoped number) and
    marking the current month partial rather than presenting it as a
    finished month's total. Deliberately never conflates this with cash
    balance (_reply_cash_balance() above) - profit/loss spans every payment
    method, cash balance only tracks Cash - see this function's own closing
    line and panda/insights.py's module docstring."""

    summary = insights.get_profit_loss_summary(admin_id)
    total_income, total_expense = summary["total_income"], summary["total_expense"]
    net = summary["net_profit"]
    monthly, current_month = summary["monthly"], summary["current_month"]

    if total_income == 0 and total_expense == 0:
        return "🐼 No income or expenses recorded yet, so there's no profit or loss to report."

    if net > 0:
        overall = f"a net profit of ₹{net:,.0f}"
    elif net < 0:
        overall = f"a net loss of ₹{abs(net):,.0f}"
    else:
        overall = "neither a profit nor a loss — you're breaking even"

    lines = [
        f"- All-time: ₹{total_income:,.0f} income − ₹{total_expense:,.0f} expense = "
        f"{overall} (every payment method combined, not just cash on hand)."
    ]

    if monthly:
        recent_months = sorted(monthly.items())[-3:]
        month_lines = []
        for month, amount in recent_months:
            if amount > 0:
                direction = f"₹{amount:,.0f} profit"
            elif amount < 0:
                direction = f"₹{abs(amount):,.0f} loss"
            else:
                direction = "broke even"
            partial_note = " (this month is still in progress)" if month == current_month else ""
            month_lines.append(f"  - {month}: {direction}{partial_note}")
        lines.append("- By month:\n" + "\n".join(month_lines))

    return "🐼 Here's your real profit/loss picture:\n" + "\n".join(lines)


def _reply_cash_management(admin_id):
    """Cash-management-topic reply (ADR-52) - composes the collection
    summary, expense breakdown, and expense-health check into one
    topic-focused message. Every sub-question in this reply already maps
    onto an existing, already-computed real number - no new query or
    calculation was written for this intent.

    The expense-category breakdown is explicitly labeled "all-time" (added
    2026-08-24) - get_expense_breakdown() has no monthly figure to show
    (get_top_expense_categories() is all-time only, see TD-61), and this
    line used to sit directly between two *this-month* figures (collection
    rate, then expense health) with nothing distinguishing it - a real audit
    of this reply flagged that a category's all-time share (e.g. "Electricity
    Bill 91.6%") reads as this month's share in that position. No underlying
    number changed, only the label."""

    collection = insights.get_cash_collection_summary(admin_id)
    expenses = insights.get_expense_breakdown(admin_id)
    health = insights.get_expense_health(admin_id)

    if collection["expected"] == 0 and not expenses:
        return "🐼 No cash activity recorded yet — nothing billed, collected, or spent so far."

    lines = []

    if collection["expected"] > 0:
        lines.append(
            f"- ₹{collection['collected']:,.0f} collected of ₹{collection['expected']:,.0f} billed "
            f"({collection['collection_pct']}% collection rate)."
        )
        if collection["pending"] > 0:
            lines.append(f"- ₹{collection['pending']:,.0f} in fees is still pending collection.")
    else:
        lines.append("- No membership fees billed yet, so there's nothing to collect against.")

    if expenses:
        top_lines = "\n".join(
            f"  - {item['category']}: ₹{item['amount']:,.0f} ({item['percentage']}%)"
            for item in expenses[:3]
        )
        lines.append(f"- Where your cash is going (top expense categories, all-time):\n{top_lines}")
    else:
        lines.append("- No expenses recorded yet.")

    lines.append(
        f"- Expense health this month: {health['status']} "
        f"(spending {health['ratio_pct']}% of this month's income)."
    )

    return "🐼 Here's your real cash picture:\n" + "\n".join(lines)


def _reply_expenses(admin_id):
    """Expense-topic reply (added 2026-08-24, closing the audit's top-ranked
    coverage gap) - composes the same expense-category breakdown and
    expense-health check _reply_cash_management() already uses, minus the
    fee-collection section (a different question - see that function). No
    new query: both insights.get_expense_breakdown()/get_expense_health()
    already existed and were already being computed, just previously only
    reachable through cash-flavored wording."""

    expenses = insights.get_expense_breakdown(admin_id)
    health = insights.get_expense_health(admin_id)

    if not expenses:
        return "🐼 No expenses recorded yet."

    top_lines = "\n".join(
        f"  - {item['category']}: ₹{item['amount']:,.0f} ({item['percentage']}%)"
        for item in expenses[:3]
    )
    lines = [
        f"- Your biggest expense categories (all-time):\n{top_lines}",
        f"- Expense health this month: {health['status']} "
        f"(spending {health['ratio_pct']}% of this month's income).",
    ]

    return "🐼 Here's your real expense picture:\n" + "\n".join(lines)


def _reply_admissions(admin_id):
    """Admissions-topic reply - broadened 2026-08-24 to also report this
    admin's total roster size and best admission month, closing the "how
    many students do I have?"/"which month had the most admissions?"/"are
    admissions increasing?" gaps the audit found: previously this only ever
    compared the latest two calendar months. Still one query for the trend
    itself - get_admissions_trend() already returns every month it has, the
    "best month" line just reads more of the same dict rather than only its
    last two entries. get_student_count() is a second, trivial query (a
    plain len() over get_admin_students(), already used elsewhere in this
    same module) - a genuinely different fact (total headcount) from the
    trend, not a substitute for it."""

    trend = insights.get_admissions_trend(admin_id)

    if not trend:
        return "🐼 No admissions recorded yet."

    months = sorted(trend.items())
    latest_month, latest_count = months[-1]
    best_month, best_count = max(trend.items(), key=lambda item: item[1])
    student_count = insights.get_student_count(admin_id)

    if len(months) < 2:
        lines = [f"🐼 {latest_count} new admission(s) in {latest_month}."]
    else:
        previous_month, previous_count = months[-2]
        if latest_count > previous_count:
            direction = "up"
        elif latest_count < previous_count:
            direction = "down"
        else:
            direction = "flat"
        lines = [
            f"🐼 Admissions are {direction} this month: {latest_count} new admission(s) "
            f"in {latest_month} (vs {previous_count} in {previous_month})."
        ]
        if best_month != latest_month:
            lines.append(f"Your best month so far was {best_month} with {best_count} new admission(s).")

    lines.append(
        f"You have {student_count} student(s) on your roster in total "
        "(all-time, including students with lapsed memberships)."
    )

    return " ".join(lines)


def _reply_purpose_performance(admin_id):
    rows = insights.get_purpose_performance(admin_id)

    if not rows or rows[0]["students"] == 0:
        return "🐼 No student purpose data yet."

    top = rows[0]
    return (
        "🐼 There's no separate batch or course list in this app, but by purpose "
        f"category, \"{top['purpose']}\" has the most students ({top['students']}) "
        f"and ₹{top['revenue']:,.0f} in revenue — the closest real answer I have."
    )


def _reply_forecast(admin_id):
    revenue = insights.get_revenue_forecast(admin_id)
    occupancy = insights.get_seat_demand_forecast(admin_id)
    churn = insights.get_churn_forecast(admin_id)

    if revenue is None and occupancy is None and churn is None:
        return (
            "🐼 I don't have enough months of real history yet to forecast anything "
            "reliably — I need at least a few months of real activity first. In the "
            "meantime, ask me about your current revenue trend, occupancy, or "
            "upcoming renewals instead."
        )

    lines = []

    if revenue is not None:
        lines.append(
            f"- Revenue: trending {revenue['trend_direction']}, roughly "
            f"₹{revenue['projected_amount']:,.0f} projected next month (based on "
            f"the last {revenue['months_used']} months)."
        )
    else:
        lines.append("- Revenue: not enough months of real income history yet to project.")

    if occupancy is not None:
        lines.append(
            f"- Occupancy: trending {occupancy['trend_direction']}, roughly "
            f"{occupancy['projected_occupancy_pct']}% projected next month."
        )
    else:
        lines.append("- Occupancy: not enough months of real history yet to project.")

    if churn is not None:
        lines.append(
            f"- Renewals: of the {churn['upcoming_expiring']} membership(s) expiring "
            f"in the next 30 days, roughly {churn['projected_lapses']} may not renew "
            f"(a recent lapse rate around {churn['projected_churn_rate_pct']}%)."
        )
    else:
        lines.append("- Renewals: not enough months of real lapse history yet to project.")

    return (
        "🐼 Here's a simple trend projection from your own real history — not a "
        "guarantee, just where the numbers have been heading:\n" + "\n".join(lines)
    )


def _reply_recommend(admin_id):
    items = insights.get_recommended_actions(admin_id)
    lines = "\n".join(f"- {item['title']}: {item['description']}" for item in items)
    return "🐼 Here's what I'd focus on right now:\n" + lines


def _reply_nav_help(admin_id):
    return "🐼 Go to Students → Admission to add a new student."


def _reply_greeting(admin_id):
    return (
        "🐼 Hi, I'm Panda! I can answer real questions about your revenue "
        "trend (and why it moved), seat occupancy, upcoming membership "
        "renewals, student retention, cash management, what to focus on "
        "next, and a simple trend projection for next month — for anything "
        "else, check Dashboard or Business Intelligence."
    )


_HANDLERS = {
    INTENT_ACTION_REQUEST: _reply_action_request,
    INTENT_EXPLAIN_REVENUE: _reply_explain_revenue,
    INTENT_REVENUE: _reply_revenue,
    INTENT_OCCUPANCY: _reply_occupancy,
    INTENT_RENEWALS: _reply_renewals,
    INTENT_ADMISSIONS: _reply_admissions,
    INTENT_PURPOSE_PERFORMANCE: _reply_purpose_performance,
    INTENT_RISK_STUDENTS: _reply_risk_students,
    INTENT_RETENTION: _reply_retention,
    INTENT_FORECAST: _reply_forecast,
    INTENT_RECOMMEND: _reply_recommend,
    INTENT_CASH: _reply_cash_management,
    INTENT_CASH_BALANCE: _reply_cash_balance,
    INTENT_PROFIT_LOSS: _reply_profit_loss,
    INTENT_EXPENSES: _reply_expenses,
    INTENT_NAV_HELP: _reply_nav_help,
    INTENT_GREETING: _reply_greeting,
}


def generate_reply(admin_id, text):
    """Panda's real reply engine (Parts 1-5, ADR-47/48/49/50/51). Classifies
    `text` into one of the intents above and returns a reply built from
    this admin's real data; a genuinely unrecognized question falls through
    to prompts.generate_placeholder_reply() rather than a fabricated
    answer."""

    handler = _HANDLERS.get(detect_intent(text))
    if handler is None:
        return prompts.generate_placeholder_reply(text)

    return handler(admin_id)
