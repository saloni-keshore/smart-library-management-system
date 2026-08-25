# Panda — Smart Business Assistant — Specification (Current State)

**Product:** Smart Library Management System · **Assistant:** Panda (Smart Business Assistant)
**Status:** Real chat interface, real persistence, and real rule-based insights are implemented and working. As of 2026-08-19, all five parts of the capability progression below are real — "Ask" (ADR-47), "Analyze" (ADR-48), "Explain" (ADR-49), "Recommend" (ADR-50), and now "Forecast" (ADR-51): a rule/keyword-based intent classifier answers revenue, occupancy, renewals, admissions trend, purpose/course performance, student-risk, "why is my revenue X", "how can I increase profit"/"what should I do", and "what's expected next month" questions with this admin's actual data, and declines action requests. **No ML or LLM is wired in — Part 5's "forecast" is a plain linear trend extrapolation over real historical data, not a trained model. Those two specific pieces (ML, LLM) are not implemented and were never required for any of the five parts.**

This document replaces the earlier "Panda AI Assistant — Technical & Functional Specification v1.0" PDF, which described Machine Learning, time-series forecasting, and an LLM as if they were already built. Those three specific capabilities do not exist in the codebase today, so Panda is renamed here from "AI Assistant" to **"Smart Business Assistant"** — a name that doesn't claim AI/LLM-level intelligence it doesn't have. This rewrite states only what is actually implemented, verified directly against `panda/*.py`, `database/ai_center_queries.py`, `requirements.txt`, and the project's own `docs/DECISIONS.md` (ADR-39, ADR-40, ADR-43) and `docs/11_FUTURE_WORK.md` (PF-7, PF-8, TD-51, TD-52, TD-55).

---

## 1. Vision

Panda is **not** merely a UI shell — it is a working feature with four real, functioning parts:

1. A floating chat widget and slide-out panel, present on every authenticated page, that sends and persists real messages.
2. A real multi-conversation chat history store (Supabase-backed, admin-scoped).
3. Real rule-based business insights, computed live on every request from the app's existing revenue/occupancy/renewal data.
4. A real rule/keyword-based chat reply engine (Parts 1-5, see PANDA_SPEC.md's progression below) that answers most of §2's example questions from this admin's actual data, including a plain-trend "what's expected next month" projection — not a generated, free-form answer.

What it does **not** have is any machine learning or language-model layer — every chat reply today is composed from a fixed template plus real numbers, never a generated sentence. The architecture is deliberately built so that adding a real language model later touches only `panda/prompts.py` and `panda/intents.py`'s handler bodies (or `panda/forecasting.py`'s three functions, for a real predictive model), without changing routes, the frontend, persistence, or the insights logic.

## 2. Primary Goals

The UI is designed to eventually let a library owner ask things like:

- Why is revenue decreasing?
- Which students are likely to leave?
- What should I do today?
- Which locality gives me the highest admissions?
- How can I increase profit?
- What is expected next month?
- Which batch should I promote?

**As of Parts 1-5 (the full "Ask"/"Analyze"/"Explain"/"Recommend"/"Forecast" progression), a narrower, real version of nearly all of these is answerable:**

- "What's my revenue trend?" and "How's my seat occupancy?" — real data (Part 1).
- "Which students are likely to leave?" — a real top-3 High-risk list, reusing AI Center's own scoring (Part 2).
- "Which batch should I promote?" — answered via purpose-category data (the closest real equivalent), with an explicit disclaimer that it isn't literally a batch answer (Part 2).
- "How many admissions this month?" / "best performing course?" — real data (Part 2).
- "Why is revenue decreasing?" (or increasing) — a real, ranked list of contributing factors (new-admissions momentum, unrenewed expired memberships, pending fee collection), each surfaced only when it points the same direction as the actual change (Part 3).
- "What should I do today?" / "How can I increase profit?" — a real, ranked list of action items, reusing Business Intelligence's existing Action Center verbatim (expiring memberships, pending fees, expense ratio, retention, revenue growth) — not a separate reasoning path from Part 3's factors (Part 4).
- "What is expected next month?" — a real, simple linear trend projection over this admin's own revenue/occupancy/renewal-lapse history for the last 6 calendar months, honestly reporting "not enough history yet" per area if fewer than 3 of those months have real data (Part 5).

- "How can I retain students?" / "How do I reduce churn?" / "How can I keep students longer?" / "How can I improve student retention?" / "What can I do to stop students leaving?" — a real retention ratio, churn trend, and top-risk-student list composed into one reply (ADR-52, 2026-08-20). This is a lateral expansion of Part 1's keyword coverage, not a new part of the progression.
- "How can I manage cash?" / "How is my cash flow?" / "How can I improve cash collection?" / "Where is my cash going?" / "How can I reduce pending fees?" — a real fee-collection rate, expense-category breakdown, and expense-health check composed into one reply (ADR-52, 2026-08-20). Same lateral expansion, not a new part.
- "How much cash do I have?" / "What's my cash balance?" / "What's in my cashbox?" / "How much physical cash do I have?" — a single real number, Cash-payment-method income minus Cash-payment-method expense, all-time; never called "bank balance"/"total money available"/"total collections" (ADR-55, 2026-08-25). "Tell me about my profit or loss" / "Am I making a profit?" / "Is my business profitable?" / "How much did I lose?" — a real all-time net (income minus expense, every payment method) plus a recent-months breakdown, with the current month explicitly marked as still in progress (ADR-55, 2026-08-25). Kept as two separate replies, deliberately never merged — a real library can be cash-positive while running an overall loss at the same time, since cash balance is Cash-only and profit/loss spans every payment method. Same lateral expansion as retention/cash-management above, not a new part.

**Still not fully answerable:** "Which locality gives me the highest admissions?" stays unanswered on purpose — no locality/city data exists anywhere on `students`, so it still gets the generic placeholder rather than a real-but-locality-less trend. Part 3's revenue explanation can only say *that* admissions/renewals/collection moved, never *which Cashbook income category* did — there's no monthly category breakdown anywhere in this codebase (see TD-61 in `docs/11_FUTURE_WORK.md`). Part 4's recommendations are the existing Action Center's general financial/retention checks — they aren't derived from Part 3's revenue factors (one of those, admissions momentum, has no real matching action anywhere in the codebase) and don't yet cover occupancy-specific advice. Part 5's forecast is a straight-line extrapolation, not a real statistical/ML model — no seasonality, no confidence interval, and small-sample-sensitive (see TD-62). The retention reply (ADR-52) can only report *that* students are at risk and by which per-student signal — it can't yet say *why*, in aggregate, across the whole at-risk roster (e.g. "most of your at-risk students are late on payment") — see TD-65.

## 3. System Architecture (as built)

```
User
 ▼
Panda Chat Widget (static/js/panda.js, templates/components/panda_widget.html)
 ▼
panda/routes.py  (Flask blueprint, /panda/*)
 ▼
panda/services.py  (send_message → intents.generate_reply)
 ├─ panda/intents.py       → keyword-based intent classifier
 │                           (ADR-47/48/49/50/51); real replies for
 │                           revenue/why-revenue/occupancy/renewals/
 │                           admissions/purpose-performance/student-risk/
 │                           recommend/forecast via panda/insights.py,
 │                           decline for action requests, falls through to
 │                           panda/prompts.py for anything unrecognized
 ├─ panda/prompts.py       → fallback: one fixed reply string for a
 │                           genuinely unrecognized message
 ├─ panda/insights.py      → wraps database/bi_queries.py (revenue,
 │                           occupancy, admissions, purpose, action items)
 │                           and database/cashbook_queries.py (pending
 │                           fees); loops database/ai_center_queries.py's
 │                           single-student compute_student_risk() for a
 │                           real top-N High-risk list (capped at 100
 │                           students); composes admissions/renewals/
 │                           pending-fee signals into a ranked "why revenue
 │                           moved" factor list; wraps Business
 │                           Intelligence's Action Center for "what should
 │                           I do" replies; wraps panda/forecasting.py for
 │                           "what's expected next month" replies
 ├─ panda/forecasting.py   → simple linear trend extrapolation (plain
 │                           Python, no ML library) over real monthly
 │                           revenue/occupancy/lapse-rate history; returns
 │                           None (never a fabricated number) below 3
 │                           months of real data
 ├─ panda/notifications.py → 3 rule-based threshold checks over existing
 │                            Dashboard/BI/Notification data (revenue trend,
 │                            expiring memberships, seat under-utilization)
 └─ database/panda_queries.py → Supabase chat history (panda_conversations,
                                 panda_messages)
 ▼
Supabase (Postgres)
```

There is no "AI Prediction Model" component in the sense the original spec meant (a trained model) — `panda/forecasting.py`'s trend extrapolation is real and wired in (see §14), but it is arithmetic over historical data, not a model with learned parameters. There is also no SQLite (SQLite was removed from this codebase entirely — Supabase/Postgres is the only database).

### Implementation status: code vs. deployment

Three distinct states apply to Panda's pieces — don't conflate "written" with "working for every install":

| Piece | In code? | Live for every install? |
|---|---|---|
| Chat widget UI, send/receive flow | ✅ Yes | ✅ Yes |
| "Today's AI Insights" (3 rule-based checks) | ✅ Yes | ✅ Yes — reads existing tables, nothing new to deploy |
| Chat history persistence (`panda_conversations`/`panda_messages`) | ✅ Yes (`database/panda_queries.py`) | ⚠️ **Only after a one-time manual step** — these two Supabase tables must be created by hand via the SQL in `database/supabase_migration.sql` (this app has no way to run DDL itself, ADR-14/43). Until then, every chat-history read/write raises `ChatStorageUnavailable` and the route returns HTTP 503 (TD-55) |
| Intent classification + reply (`panda/intents.py`) | ✅ Yes | ✅ Yes — revenue/why-revenue/occupancy/renewal/admissions/purpose-performance/student-risk/recommend/forecast questions get a real answer; action requests are declined; locality questions stay honestly unanswered (no locality data exists) |
| Placeholder fallback (`generate_placeholder_reply`) | ✅ Yes | ✅ Yes — for a message `intents.py` doesn't recognize at all; always the same fixed string, nothing pending deployment |
| Forecasting (`panda/forecasting.py`) | ✅ Yes — real plain-Python linear trend extrapolation | ✅ Yes — reads existing tables, nothing new to deploy; returns `None` (not a fabricated number) when an admin has fewer than 3 real months of history in a given area |
| ML / LLM / time-series (a trained model) | ❌ No code exists at all | ❌ No |

## 4. Security Architecture

The intended boundary is unchanged from the original spec — Panda should never delete records, modify tables, execute AI-generated SQL, change settings, access credentials, or run system/shell commands, and should only read approved analytics data.

**Important caveat:** this boundary holds today only because **no tool-calling code path exists at all** — there is nothing capable of violating it, not an active runtime filter. `panda/prompts.py`'s `READ_ONLY_RULES` is documentation for a future LLM/tool-calling layer, not an enforcement mechanism today (ADR-43). It must be re-verified as a real guard once a tool-calling layer is actually added.

## 5. Read-Only Principle

Same caveat as §4: true by construction (nothing writes anything except Panda's own chat log), not by an active check.

## 6. Action Approval Rule

**Implemented as of Part 1 (ADR-47).** `panda/intents.py` detects deletion wording ("delete", "remove", "cancel", "terminate") and pricing-change wording (a change verb like "increase"/"set" combined with "fee"/"price"/"rate") and declines with a message pointing back to the app's own screens. "Delete Rahul Sharma" and "Increase all membership fees" both get this decline reply, not the generic placeholder — this check runs before every other intent, since misclassifying an action request as an answerable question would be a security-relevant mistake. There's still no impact-estimation offer for a specific proposed action (e.g. actually projecting *this particular* fee-increase's revenue effect before declining) — Part 4 ("Recommend", now built) surfaces general real action items (expiring memberships, pending fees, expense ratio, retention, revenue growth), not a per-action "what would happen if I did X" projection; that remains unbuilt.

## 7. AI Learning

**Not implemented.** Nothing in the codebase analyzes historical data to learn patterns (admissions seasonality, renewal behavior, purpose trends, etc.). This section is a future goal, not a current capability.

## 8. AI Models (current reality)

| Technique | Status | Notes |
|---|---|---|
| Rule-Based Engine | **Real, in use today** | AI Center's student retention-risk score (weighted sum of 3 signals, ADR-39); Panda's "Today's AI Insights" (3 threshold checks); Business Intelligence's health score / action items |
| Machine Learning (Random Forest) | **Not implemented** | No `scikit-learn` dependency. ADR-39 explicitly rejected ML: no labeled churn outcome exists anywhere in the schema to train against |
| Time Series Forecasting | **Real, but simple — a straight-line fit, not a statistical/ML forecasting method** | `panda/forecasting.py`'s `forecast_revenue`/`forecast_membership_churn`/`forecast_seat_demand` (ADR-51) fit a plain-Python ordinary-least-squares line through up to 6 months of real history and project one month ahead. No `scikit-learn`/`statsmodels`/`prophet` — no seasonality, no confidence interval (see TD-62 in `docs/11_FUTURE_WORK.md`) |
| LLM | **Not implemented** | `generate_placeholder_reply()` returns one fixed string for every message; no OpenAI/Anthropic/Azure API call exists anywhere in the codebase |

## 9. Knowledge Sources (current reality)

Panda's "Today's AI Insights" cards read: **Revenue** (trend), **Occupancy** (seat under-utilization), **Membership renewals** (expiring soon) — via existing `bi_queries`/`notification` query functions (unchanged since Part 1).

Panda's chat replies (Parts 1-5) additionally read: **Admissions** (monthly new-membership counts), **Purpose** (per-category student count/revenue, also used for "batch" questions), **Risk Scores** (by reusing AI Center's existing per-student `compute_student_risk()`, capped at 100 students per reply — see TD-60), **Pending Fees** (billed-but-uncollected `memberships.pending_amount` total, via `database/cashbook_queries.get_pending_fees()`, for the revenue-explanation factor list — Part 3's one new data source beyond what Parts 1-2 already read), **Action Items** (Business Intelligence's own Action Center — expiring memberships, pending fees, expense ratio, retention, revenue growth — via `database/bi_queries.get_action_items()`, reused verbatim for Part 4's recommend reply), and **6-Month Historical Trends** (monthly Cashbook income, monthly occupancy %, and a newly-computed monthly membership-lapse rate — `panda/forecasting.py`, Part 5's own forecasting engine, the one place in this progression that computes something genuinely new rather than only reusing an existing function's output).

As of 2026-08-20 (ADR-52, the retention/cash topic expansion), Panda's chat replies additionally read: **Membership Retention Ratio** (total vs. currently-active memberships, `database/bi_queries.get_membership_retention()` — already computed there for the Action Center/health score, now also exposed directly), **Fee Collection Summary** (expected vs. collected vs. pending fee revenue and the collection %, `get_revenue_collection_summary()`), **Expense Category Breakdown** (this admin's real expense categories ranked by amount, `get_top_expense_categories()` — all-time, not monthly, same limitation TD-61 already documents for income categories), and **Expense Health** (this month's expense-to-income ratio classification, `classify_expense_health()`) — all four already computed for Business Intelligence's own pages, none of them newly queried for this addition.

As of 2026-08-25 (ADR-55, the cash-balance/profit-loss topic expansion), Panda's chat replies additionally read directly from Cashbook itself: **Cash Balance** (Cash-payment-method income minus Cash-payment-method expense, all-time, `database/cashbook_queries.get_cash_balance()` — all-time only, no monthly breakdown exists, see TD-71) and **Profit/Loss** (all-time net plus a per-month breakdown, `database/cashbook_queries.get_total_income()`/`get_total_expense()`/`get_monthly_profit()`) — all pre-existing Cashbook functions, none newly written for this addition.

Panda does **not** currently read: Payments detail, Marketing/locality data (none exists in the schema), any data beyond 6 months back (Part 5's forecast window), or any monthly (as opposed to all-time) cash balance or income/expense category breakdown (TD-61/TD-71).

## 10. Example Workflow (as it actually runs)

```
1. USER TYPES A MESSAGE
   ↓
2. panda/services.py's send_message() is called
   ↓
3. panda/intents.py's generate_reply() classifies the message
   (keyword matching, no LLM) into one of:
     a. Revenue / why-revenue / occupancy / renewals / admissions /
        purpose-performance / student-risk / recommend / forecast →
        real reply, built from panda/insights.py's live data for this admin
     b. Action request (delete/pricing) → decline + redirect reply
     c. Unrecognized → prompts.generate_placeholder_reply()'s fixed string
   ↓
4. Reply + user message persisted to panda_conversations/panda_messages
   (requires the Supabase tables to have been created manually — see §17)
   ↓
✓ REPLY SHOWN TO USER
```

There is still no LLM composition step — "Workflow B" from the original spec describes an LLM-composed answer that doesn't exist. "Workflow A" (a prediction/forecast step) now genuinely exists, just not as a trained model — step 3's real backend data-collection now covers all nine answerable intents, including a real "why" narrative for revenue (Part 3), a real ranked action-item list for "what should I do" (Part 4), and a real trend projection for "what's expected next month" (Part 5, `panda/forecasting.py` - simple linear extrapolation, not a prediction model).

## 11. Notifications / Daily Business Brief

**Not implemented.** No login-time check runs across Revenue/Admissions/Predictions/Renewals/Occupancy, and no daily brief is generated anywhere in the codebase. Kept here only as a described, unbuilt feature idea.

## 12. AI Chat Capabilities

**Nearly all of the example questions in the original spec are now genuinely answerable; the rest say so honestly rather than faking it.** "Show high risk students" now gets a real top-3 High-risk list (Part 2), not a redirect. "Best performing course?" gets a real answer via purpose-category data (Part 2). "Why is revenue decreasing?" now gets a real, ranked list of contributing factors instead of just the trend figure (Part 3). "How can I increase profit?"/"What should I do today?" now get a real, ranked action-item list instead of a placeholder (Part 4). "What's expected next month?"/"forecast revenue" now get a real, simple linear trend projection instead of a placeholder (Part 5) — or an honest "not enough history yet" line for a fresh admin, never a fabricated number. Revenue trend and seat occupancy questions get a real, data-backed reply (Part 1). "How can I retain students?"/"how do I reduce churn?" and "how can I manage cash?"/"where is my cash going?" now get a real, topic-focused reply too (ADR-52, 2026-08-20) — a lateral expansion of Part 1's keyword coverage, not a new part of the progression. A question with no matching intent at all (e.g. "which locality gives me the highest admissions") still falls to the generic placeholder.

## 13. Recommendation Engine

**Partially implemented, as of Part 4 (ADR-50).** `panda/insights.py`'s `get_recommended_actions()` reuses Business Intelligence's existing Action Center (`database/bi_queries.get_action_items()`) verbatim — real, ranked recommendations for expiring memberships, pending fees, expense discipline, membership retention, and revenue growth, all derived from this admin's actual data. No new recommendation logic was written for this; it's the same list already shown on Business Intelligence's Overview page, now also reachable from chat. Still not implemented: Marketing, Pricing, and Seat Utilization suggestions specifically (occupancy-specific recommend questions aren't classified as recommend at all yet — see `docs/DECISIONS.md` ADR-50's "how to apply"), and any per-action impact projection (e.g. "if I raise fees by X%, revenue would change by Y" — see §6).

## 14. Forecasting

**Implemented as of Part 5 (ADR-51) — real, but a simple linear trend extrapolation, not a statistical/ML forecasting method.** `panda/forecasting.py`'s three functions — `forecast_revenue`, `forecast_membership_churn`, `forecast_seat_demand` — each fit an ordinary-least-squares straight line (plain Python, ~10 lines, no `numpy`/`scikit-learn`/`statsmodels`/`prophet`) through up to 6 months of this admin's own real historical data and project one month ahead:

- **Revenue:** fits `database/cashbook_queries.get_monthly_income()` — the same monthly Cashbook income figure `get_revenue_growth()` compares month-to-month.
- **Seat demand (occupancy):** fits `database/bi_queries.get_monthly_occupancy_trend()` — real history reconstructed from membership joining_date/end_date ranges (no seat/attendance log exists).
- **Membership churn:** computes a genuinely new monthly lapse-rate series (the one calculation in this module that isn't reusing an existing function's output) — a membership counts as "expiring" in the month its `end_date` falls in, and "lapsed" if that student has no later membership; the projected rate is applied to the real, already-existing `get_upcoming_expiries(days=30)` cohort.

Each function returns `None` — never a fabricated number — when fewer than 3 of the window's 6 months have real, nonzero data (or, for churn, real expirations) to fit a trend against. `panda/intents.py`'s `_reply_forecast()` composes whichever of the three are available, explicitly labeled "a simple trend projection... not a guarantee."

**What this is not:** no Admissions, Cash Flow, or Purpose Growth forecasting exists (only revenue/occupancy/churn, matching the original stub's three named functions). No seasonality, confidence interval, or outlier handling — a single unusual month skews the fit the same way it would skew any small-sample linear regression (see **TD-62** in `docs/11_FUTURE_WORK.md`). No trained model of any kind — "forecast" here means extending the straight line this admin's own numbers have actually been tracing, nothing more.

## 15. Personality

Unchanged from the original intent — friendly, professional, explains clearly, never robotic. The one placeholder reply that exists today is at least consistent with this tone (it honestly states it isn't connected to a real AI model yet, rather than faking an answer).

## 16. Technology Stack (what's actually installed)

| Component | Original spec claimed | Actually installed |
|---|---|---|
| Backend | Flask (Python) | ✅ Flask — true |
| Database | SQLite | ❌ SQLite was removed entirely; **Supabase/Postgres** is the only database |
| AI Models | Scikit-learn | ❌ Not in `requirements.txt` |
| Forecasting | Prophet / Statsmodels | ❌ Not in `requirements.txt` |
| Data Processing | Pandas, NumPy | ⚠️ NumPy is installed (`requirements.txt`); **Pandas is not installed at all** |
| LLM Integration | OpenAI / Azure OpenAI | ❌ No API key, no HTTP call to any LLM provider anywhere in the codebase |
| Charts | Chart.js / ApexCharts | ✅ Server-rendered via `matplotlib` (`utils/charts.py`) |
| Frontend | HTML, CSS, Bootstrap, JS | ✅ true |

## 17. Roadmap

### Built today
- Floating chat widget + slide-out panel on every authenticated page
- Persisted multi-conversation chat history (`panda_conversations`/`panda_messages`) — **requires a one-time manual Supabase table creation**; until that's applied, chat history returns an HTTP 503 (the floating button, insights, and suggested questions still work)
- "Today's AI Insights" — 3 rule-based checks (revenue trend, expiring memberships, seat under-utilization)
- Suggested Questions UI (static prompts — all seven now have a real answer behind them, see below)
- **Part 1, "Ask" (ADR-47):** a rule/keyword-based reply engine (`panda/intents.py`, no external AI API, no ML) — real answers for revenue trend, seat occupancy, and upcoming renewals; a decline-and-redirect reply for deletion/pricing-change requests; a static navigation answer for "how do I add a student"; and the original fixed placeholder for anything else
- **Part 2, "Analyze" (ADR-48):** real answers for admissions trend and purpose/course performance (reusing `bi_queries.py`'s existing functions); "which batch should I promote?" answered via the same purpose data with an explicit "not a real batch" disclaimer, since no batch concept exists in this schema; student-risk questions upgraded from a redirect to a real top-3 High-risk list (reusing AI Center's own `compute_student_risk()`, capped at 100 students per reply — see TD-60); "which locality gives the highest admissions" deliberately still unanswered — no locality data exists anywhere on `students`
- **Part 3, "Explain" (ADR-49):** real answers for "why is revenue X" — `panda/insights.py`'s `get_revenue_explanation()` composes three existing signals (new-admissions momentum, unrenewed expired memberships, pending fee collection) into a ranked factor list, each surfaced only when it points the same direction as the actual revenue change; falls back to an honest "nothing stands out" line when no signal lines up. Can only say *that* admissions/renewals/collection moved, never *which Cashbook income category* did — see TD-61
- **Part 4, "Recommend" (ADR-50):** real answers for "how can I increase profit?"/"what should I do?" — `panda/insights.py`'s `get_recommended_actions()` is a pure wrapper around Business Intelligence's existing Action Center (`get_action_items()`); no new recommendation logic, no per-factor mapping from Part 3's revenue explanation (one of its three factors, admissions momentum, has no real matching action in the codebase). Always returns at least one item — falls back to `get_action_items()`'s own honest "No urgent issues detected" filler when nothing is currently flagged. Doesn't yet cover occupancy-specific recommend questions
- **Part 5, "Forecast" (ADR-51):** real answers for "what's expected next month?" — `panda/forecasting.py`'s three functions each fit a plain-Python linear trend through up to 6 months of real revenue/occupancy/lapse-rate history and project one month ahead; returns `None` (never a fabricated number) below 3 real months of data in a given area. No seasonality, confidence interval, or ML — see TD-62
- **Retention/cash topic expansion (ADR-52, 2026-08-20):** real answers for "how can I retain students?"/"how do I reduce churn?" (retention ratio + churn trend + top-risk-student list, composed) and "how can I manage cash?"/"where is my cash going?" (fee-collection rate + expense-category breakdown + expense-health check, composed) — a lateral expansion of Part 1's keyword coverage closing one instance of TD-59, not a sixth part of the progression. No new query was written for either topic. Retention's reply doesn't attempt a cross-student "why are students at risk" aggregate — see TD-65
- AI Center (a separate module from Panda): rule-based student retention-risk scoring, with admin-configurable weights/thresholds

### Planned next slices (not yet built, closest to buildable)
- AI Center's aggregate Prediction Dashboard (portfolio-level risk counts/distribution/trend — Part 2's risk-list orchestration is Panda-scoped and capped, not this dashboard)
- Marketing intelligence (would need a real locality/geography field on `students` first — none exists today)
- A monthly Cashbook income-category breakdown (TD-61) — would let Part 3's revenue explanation name *which* category (Admission Fee vs. Renewal vs. Donation, etc.) moved, not just that admissions/renewals/collection did
- Occupancy-specific recommend questions — `get_occupancy_insights()` (`database/bi_queries.py`) already has a real actionable subset (overload/underutilized/uneven-balance items) not yet wired into Part 4's recommend reply
- A real statistical/ML forecasting layer (TD-62) — would need a new dependency (`statsmodels`/`prophet`) to add seasonality/confidence intervals beyond Part 5's plain linear fit
- A genuine LLM/tool-calling layer — the long-planned "real AI model" swap point (`panda/intents.py`'s handler bodies, or `panda/forecasting.py`'s three functions), not started; `panda/prompts.py`'s `SYSTEM_PERSONA`/`READ_ONLY_RULES` exist in anticipation of this but are not enforced by any runtime code today

### Long-term ideas — not planned, not committed
These are parked ideas only, each requiring its own separate infrastructure unrelated to finishing the chat/insights work above. They should not be read as a roadmap commitment:

- Voice conversations with Panda (speech infrastructure)
- WhatsApp integration (WhatsApp Business API)
- Multi-language support (i18n across the app)
- Email summaries (transactional email pipeline)
- Smart campaign planning (a campaign engine)
- Predictive staffing and seat planning

## 18. Closing note

This architecture is a **placeholder-safe scaffold**, now fully filled in for its originally-scoped five parts: "Ask"/"Analyze"/"Explain"/"Recommend"/"Forecast" answer nine real categories of question from this admin's actual data, using keyword matching and plain-arithmetic trend extrapolation, not an AI model — and where the real answer had to stand in for something that doesn't exist in the data (batch → purpose), or could only say part of the real picture (why revenue moved, but not which Cashbook category; what to focus on generally, but not a per-action fee-change projection; what's expected next month, but as a simple straight line, not a statistical forecast), the reply says so outright rather than pretending. It still deliberately ships no fake intelligence beyond that — a genuinely unrecognized question gets the original fixed placeholder, and a question with no real data behind it (locality) stays unanswered rather than answered wrong. Nothing in this document should be read as describing a full AI system today: there is still no ML model and no LLM anywhere in this codebase. When a real model is wired in, the intended integration points remain `panda/intents.py` (per-intent reply logic, or the classifier itself) and `panda/forecasting.py` (its three functions, for a real predictive model) — no other file should need to change for that swap.
