# Templates Reference

## Layout system (`templates/layouts/`)

**`base.html`** — the authenticated-app shell. Loads Google Font "Poppins", Bootstrap 5.3.7 + Bootstrap Icons 1.11.3 (CDN), and `static/css/style.css`. Blocks a child template can override:
- `title` (default `"Smart Library Pro"`)
- `styles` — extra `<link>` tags in `<head>` (used by page-specific stylesheets like `business_intelligence.css`)
- `content` — rendered inside `<main class="content-wrapper">`
- `scripts` — extra `<script>` tags at the end of `<body>`

Structure: `{% include 'layouts/navbar.html' %}`, then a flex row with `.sidebar-wrapper` (`{% include 'layouts/sidebar.html' %}`), a `.sidebar-backdrop` (mobile overlay), and `<main>`. An inline script wires `#sidebarToggle` to toggle mobile sidebar visibility.

Every feature page does `{% extends "layouts/base.html" %}` and overrides `title`/`content` (and often `styles`/`scripts`).

**`auth_base.html`** — separate minimal shell for `login`/`register`/`forgot_password`. Loads `css/login.css` and `js/login.js` instead of the main stylesheet; no navbar/sidebar. Blocks: `title`, `content`.

**`navbar.html`** — plain include (not block-based). Expects `session['username']` (defaults `"Admin"` in the template). Includes `components/notification_dropdown.html`. **As of 2026-08-17 (Global Search, ADR-44):** the search box (`#globalSearch`, `data-search-url="{{ url_for('search.suggestions') }}"`) is a live, grouped-by-type autocomplete — typing debounces a `fetch()` to `GET /search/suggestions?q=...` and renders matching Students/Payments/Enquiries/Cashbook entries in a dropdown (`static/js/navbar_search.js`, styled by `static/css/navbar_search.css`, both loaded from `base.html`); clicking (or arrow-key-then-Enter on) a Student/Payment/Enquiry result navigates straight to its record, typing alone never navigates, and Cashbook results are shown but not clickable (no single-entry view page exists yet — TD-56). Links to `setting.index` and `auth.logout`. Inline script fills `#currentDate` client-side.

**`sidebar.html`** — left nav. Local Jinja macro `nav_badge(count)` renders a red badge if `count > 0`. Expects `enquiries_new_count`, `students_new_today_count`, `memberships_expiring_soon_count`, `payments_pending_count` — **note:** no route or context processor currently supplies these variables (only `sidebar.html` references them), so the badges likely render blank/undefined in practice. Active-link highlighting is done inline per-link via `request.endpoint.startswith('student.')`-style checks, not a passed-in "active" flag.

## `templates/components/` (~47 shared partials)

**Generic primitives**, used via `{% include %}` with `with`, or `{% call %}` macros:
| File | Purpose |
|---|---|
| `stat_card.html` | KPI tile — icon, title, value, trend line. Params: `title, value, icon, trend, trend_color, trend_icon, col_class, accent_class` |
| `chart_card.html` | Card wrapper with header + `{{ caller() }}` body slot |
| `table_card.html` | Same caller-based wrapper, styled for tables |
| `activity_card.html` | Card meant to be `{% extends %}`-ed (has a `{% block activity %}`), not included |
| `alert.html` | **Empty file (0 bytes)** — unused placeholder |
| `dashboard_header.html`, `insights_card.html`, `quick_actions.html` | Dashboard-specific: header banner, shortcut action row. `dashboard_header.html`'s "Today's Date" block has been commented out since before this doc existed; the inline `<script>` that wrote into it (`getElementById("dashboardDate")` against a non-existent element, throwing on every Dashboard load) was dead code removed 2026-07-21 — see [CHANGELOG.md](CHANGELOG.md). `quick_actions.html`'s "New Admission" card linked to `student.index` (the Student List) instead of starting the admission workflow at its actual entry point; fixed 2026-07-25 to link to `enquiry.add`, matching the "New Enquiry" card and the documented Dashboard → New Enquiry → Save Enquiry → Convert to Student → Create Membership → Payment → Receipt → Student Profile flow — see [CHANGELOG.md](CHANGELOG.md). Its "Collect Fees" card likewise linked to `payment.index` (the generic Payments list) instead of the Student List; fixed 2026-07-25 to link to `student.index`, matching the documented Dashboard → Collect Fees → Student List → Student Profile → Collect Pending Fee → Receipt flow (per-student "Collect Payment" already exists on both `students/index.html` and `students/view.html`, routing to `payment.collect`) — see [CHANGELOG.md](CHANGELOG.md) |
| `notification_dropdown.html` | Navbar bell — expects `nav_notifications` (from `app.py`'s context processor) with `.counts`/`.buckets`/`.meta` |
| `receipt_document.html` | The single shared "professional receipt" design. Included by `payments/receipt.html` (real payment data) and `settings/receipt_settings.html` (Receipt Preview, mock literals). Caller must `{% set %}` `receipt_number, joining_date, expiry_date, issued_date, payment_mode, student_name, plan_name, amount` and have `settings` (a `library_settings` row or `None`) in scope. As of ADR-63 (2026-08-30) it shows **Joining Date** + **Expiry Date** rows (`expiry_date` may be `None` → row skipped) and an `issued_date` line by the signature, replacing the old single print-date "Date" row; `plan_name` is pre-formatted by the caller (`routes/payment.py`'s `_plan_label()` renders a Custom plan as `"Custom - N day(s)"`, and as of ADR-65 appends `" - <slot name> (<bucket>)"` when the membership was sold on a shift slot). **To change the receipt's visual design, edit only this file** — both the preview and the real receipt pick it up. |
| `revenue_chart.html`, `payment_chart.html`, `membership_chart.html`, `membership_distribution_chart.html` | Dashboard/Distribution chart cards. **As of 2026-08-28 (ADR-56)** each holds a `<canvas>` + an inline `<script>window.dashboardRevenueChart` / `dashboardMembershipChart` / `membershipDistributionChart = {{ ...|tojson }}</script>`, drawn client-side by `dashboard-charts.js` with Chart.js (was `<img src="static/charts/*.png">` when charts were server-rendered). Still wrapped in the skeleton loader (`data-chart-stage`). `revenue_chart.html`'s `#revenue-period-select` (`this_year`/`last_year`) triggers a `fetch()` of `GET /dashboard/revenue-chart?period=...` and a `chart.update()` with the returned `{labels, datasets}` |
| `expiry_table.html`, `upcoming_expiry.html`, `recent_admissions.html` | Dashboard mini-tables |
| `add_transaction_modal.html`, `edit_transaction_modal.html`, `transaction_details_modal.html` | Bootstrap modals shared by Cashbook + Dashboard quick actions, driven by `static/js/transaction_modal.js` |

**Business Intelligence (`bi_*`, 10 files)** — data from `database/bi_queries.py` via `routes/business_intelligence.py`:
| File | Purpose |
|---|---|
| `bi_health_score.html` | Circular Chart.js gauge for the composite health score/status |
| `bi_advisor.html` | Intentional "Coming Soon" placeholder — reserved for a future AI-advisor feature |
| `bi_action_center.html` | Loops `action_items` into recommendation tiles |
| `bi_health_status.html` | Compact status readout paired with the health score |
| `bi_membership_growth_chart.html`, `bi_revenue_growth.html`, `bi_revenue_trend_chart.html` | Chart.js canvas cards for growth/trend metrics |
| `bi_timeline.html` | Chronological activity feed |
| `bi_top_expense.html`, `bi_top_revenue.html` | Ranked top-category list cards |

All ten of the above are Overview-only (included directly by `business_intelligence/index.html`, unchanged 2026-07-25). A separate, module-wide file sits alongside them:

| File | Purpose |
|---|---|
| `bi_components.html` | **Added 2026-07-25.** Macro file (`{% import ... as bi %}`, not `{% include %}`) shared by **all four** BI pages (Overview + the three new ones below). Exports `tabs(active)` (the module's top nav bar — Overview/Purpose Analytics/Revenue Analytics/Occupancy Analytics), `analytics_header(title, subtitle)`, `kpi_card(label, value, icon, accent, col)`, `chart_card(title, subtitle, col, size, sample=True)` (`{% call %}`-style, caller supplies the `<canvas>`), `insight_card(label, value, description, icon, accent, col)`, `analytics_table(title, subtitle, sample=True)` (`{% call %}`-style, caller supplies `<thead>`/`<tbody>`). `sample=False` (all three sibling pages pass this on every call, as of 2026-07-26) renders a "Live Data" badge instead of the default "Sample data" one. Styled entirely by `static/css/business_intelligence.css`'s `.bi-tab*`, `.bi-kpi-*`, `.bi-insight-*`, `.bi-table*` rules (same file the Overview page already used, extended not replaced). |

**Cashbook (`cashbook_*`, 6 files)**:
| File | Purpose |
|---|---|
| `cashbook_summary_cards.html` | Two rows of `stat_card` includes — today's Income/Expense/Profit/Cash Balance, then all-time totals/pending/today's count |
| `cashbook_charts.html` | Revenue-by-source and payment-method donut Chart.js canvases |
| `cashbook_filters.html` | GET filter form (search, date range/preset, type, category, method, source) |
| `cashbook_expense_chart.html`, `cashbook_income_chart.html` | Individual breakdown chart cards |
| `cashbook_activity_log.html`, `cashbook_transactions.html` | Transaction/activity list tables |

**Membership (`membership_*`, 8 files)**:
| File | Purpose |
|---|---|
| `membership_summary_cards.html` | `stat_card` includes for per-plan counts + Active/Expired |
| `membership_chart.html` | Dashboard card showing static `charts/membership.png`, links to `membership_distribution.index` |
| `membership_distribution_table.html` | Full data table for the distribution page (Library ID, Student, Mobile, Plan, dates, Status, Pending, Actions) |
| `membership_distribution_chart.html` | Donut chart card (`membership_distribution_donut.png`) for the distribution page |
| `membership_filters.html` | Filter form, same convention as `cashbook_filters.html` |
| `membership_progress.html`, `membership_quick_insights.html` | Progress bar / quick-insight summary widgets |

## Feature template folders

| Folder | Templates |
|---|---|
| `auth/` | `login.html`, `register.html`, `forgot_password.html` |
| `dashboard/` | `index.html` |
| `enquiries/` | `index.html`, `add.html`, `edit.html`, `view.html` — **as of 2026-08-28 (ADR-58):** `edit.html` is also rendered by `enquiry.re_enquire` with `reenquiry=True` (heading "Log New Enquiry for <name>", read-only mobile, "Log Enquiry" button); `view.html` has a "Log Another Enquiry" button (`enquiry.re_enquire`) |
| `students/` | `index.html`, `admission.html`, `view.html`, `edit.html` — **as of 2026-08-28 (ADR-58):** `view.html` has a "Log Another Enquiry" button (`enquiry.re_enquire`, shown only when `student.enquiry_id` is set). **As of 2026-08-30 (ADR-61):** `index.html` renders an amber "Pending" status badge (checked before the Inactive branch), a "Complete Admission" row action (→ `membership.create`) for a `Pending` student with no membership, and a dismissible "N admissions are incomplete" banner driven by `incomplete_count`; `view.html` badges `Pending` amber and shows a "Complete Admission" button when `status == "Pending"` and no membership; `edit.html`'s status `<select>` has a `Pending` option; `admission.html` has a note that the student stays Pending until membership + full payment and that Back creates nothing |
| `memberships/` | `index.html`, `create.html`, `renew.html`, `distribution.html`, `analytics.html` |
| `payments/` | `index.html`, `collect.html`, `receipt.html` — note `create.html` still exists but no route renders it (TD-11); `success.html` is gone, replaced 2026-07-25 by `receipt.html` (rendered by `routes/payment.py`'s new `receipt()`) |
| `cashbook/` | `index.html`, `transactions.html`, `analytics.html` — only `index.html` is rendered by `routes/cashbook.py`; `transactions.html`/`analytics.html` appear to be leftover/unwired |
| `business_intelligence/` | `index.html` (Overview), plus `purpose_analytics.html`, `revenue_analytics.html`, `occupancy_analytics.html` (added 2026-07-25, UI-only — see below) |
| `notification/` | `index.html` |
| `settings/` | `index.html`, `library_profile.html`, `membership_settings.html`, `receipt_settings.html`, `notification_settings.html`, `staff_access.html`, `data_backup.html`, `security_settings.html` — every Settings sub-page now has a template, no stubs remain |
| `reports/` | `index.html` — unreferenced (see `routes/report.py`, a pure redirect shim) |

See [11_FUTURE_WORK.md](11_FUTURE_WORK.md) for the unwired-template list.

### Business Intelligence module templates, in detail

Added 2026-07-25 to turn Business Intelligence from a single page into a tabbed module. The sidebar still has exactly one "Business Intelligence" entry (unchanged); navigation between the four pages happens entirely inside the module via the tab bar in `components/bi_components.html`'s `tabs()` macro, rendered at the top of every one of the four pages below.

- **`index.html`** (Overview, **not redesigned**) — the only change is one added line, `{{ bi.tabs('overview') }}`, right after the flashed-messages block and before its existing `.bi-section` header. Every `bi_*` component it already included is untouched.
- **`purpose_analytics.html`** (real data since 2026-07-26, Phase 1) — `bi.analytics_header()`; a 5-card `bi.kpi_card()` row (Total Students, Total Revenue, Top Purpose, Top Revenue Purpose, Average Revenue Per Student); two `bi.chart_card()` rows (Students by Purpose bar + Purpose Distribution doughnut, then Revenue by Purpose bar + Revenue Distribution doughnut); a "Business Insights" row of four `bi.insight_card()`s (Highest/Lowest Students, Highest/Lowest Revenue) plus one hand-rolled recommendation card; and a `bi.analytics_table()` ("Purpose Summary": Purpose, Students, Student %, Revenue, Revenue %, Average Revenue). Charts render via `static/js/bi_purpose_analytics.js` against `window.biPurposeChartData`, sourced from `_purpose_analytics_data()`/`database/bi_queries.py`'s `get_purpose_breakdown()`.
- **`revenue_analytics.html`** (real data since 2026-07-26, Phase 2, ADR-37) — a 5-card KPI row (Total/Today's/This Week's/This Month's/This Year's Revenue) plus a second 5-card row (Expected/Collected/Pending Revenue, Collection %, Avg Revenue/Student); a large-size `bi.chart_card()` row (Revenue Trend line + Monthly Revenue bar, 12 months); a second chart row (Revenue by Membership doughnut + Revenue by Purpose doughnut); a third chart row (Revenue by Payment Mode doughnut + New Admissions vs Renewal doughnut); a "Business Insights" row of four `bi.insight_card()`s (Highest Revenue Purpose/Plan, Fastest Growing Month, Most-Used Payment Mode) plus one hand-rolled Collection Rate card; and a `bi.analytics_table()` ("Revenue Table": Month, Revenue, Expense, Profit). Charts render via `static/js/bi_revenue_analytics.js` against `window.biRevenueChartData`, sourced from `_revenue_analytics_data()`/`database/bi_queries.py`'s revenue helpers.
- **`occupancy_analytics.html`** (real data since 2026-07-26, Phase 3, ADR-38; ADR-67 added Night 2026-09-02) — a 5-card KPI row (Total Seats, Occupied Seats, Available Seats, Overall Occupancy %, Peak Shift) plus a second row of per-shift Occupancy % cards, now **four** (Morning/Afternoon/Evening/**Night**); a chart row (Shift Distribution doughnut + Seat Utilization stacked bar); three hand-rolled shift cards (Morning/Afternoon/Evening, each a mini Chart.js doughnut ring showing occupied vs. available, seeded from the admin's own configured seat capacity); a full-width large `bi.chart_card()` (Monthly Occupancy Trend line, 6 months); a chart row (Purpose vs Shift stacked bar + Membership vs Occupancy bar); an `{% include "components/bi_occupancy_insights.html" %}` AI Insights section (rule-based, `.bi-action-item`-styled); two `bi.insight_card()`s (Occupancy by Membership Plan, Occupancy by Purpose); a `bi.analytics_table()` ("Shift Utilization": Shift, Capacity, Occupied, Available, Utilization); and a second `bi.analytics_table()` ("Purpose Shift Matrix": Purpose, one column per shift (dynamic — grows an "Other" column only if populated), Total). Charts render via `static/js/bi_occupancy_analytics.js` against `window.biOccupancyChartData`, sourced from `_occupancy_analytics_data()`/`database/bi_queries.py`'s occupancy helpers.

**All three pages now render real, admin-scoped data — none are placeholders.** Each route builds a dict → the template dumps it into a `window.*ChartData` JS global → a page-specific JS file renders Chart.js canvases from it, the same shape `index.html`/`business_intelligence.js` already used. See TD-46 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md) for the full history of this rollout across its three phases.

### Settings templates, in detail

- **`notification_settings.html`** (new) — sectioned like `receipt_settings.html`: Reminder Rules (7/3/1-day toggles + notify-on-expiry-day/notify-after-expiry), Notification Channels (In-App plus SMS/Email/WhatsApp, the latter three each marked "Integration coming soon. This only saves the preference."), Quiet Hours (enable switch + start/end time inputs, disabled client-side via `static/js/settings.js` when the switch is off, + allow-critical-alerts switch), Dashboard Notifications (6 show/hide toggles), a static dummy "Notification Preview" card (Expiry Reminder / Payment Pending / New Admission examples, not real data), and the same "Configuration Changes" diff-table component used by Membership/Receipt Settings. Form id `notificationSettingsForm`.
- **`staff_access.html`** (new) — pure placeholder, no form. Explains the single-admin limitation and previews 4 future roles (Owner, Front Desk, Accountant, Librarian) as static cards. See PF-4 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md).
- **`data_backup.html`** (new) — three stat cards (Current Database Size, Last Backup Date, Backup Location) fed by `routes/setting.py`'s `data_backup()`, plus two actions: `Export CSV` (`backup_export_csv`) and a `Create Backup` POST form (`backup_create`). A note calls out that automatic backups aren't implemented yet (PF-5).
- **`security_settings.html`** (new) — two forms distinguished by a hidden `form_type` field: "Change Password" (`form_type=password`, id `securityPasswordForm`, client-side new/confirm match check via `static/js/settings.js`) and "Session Preferences" (timeout `<select>`, remember-me switch, login-notifications switch). A static "Future Security Features" card lists 2FA and Device Management as visual-only "Coming Soon" rows.
- **`membership_settings.html`** (modified) — the `reminder_days`/`send_reminders` input+switch were removed; replaced with a read-only "Reminders & Notifications" card. **As of 2026-09-02 (ADR-66):** an "Extra charges" card added — amount inputs for `seat_reservation_fee`/`locker_fee`/`security_deposit_amount` and Compulsory switches for all four charges (`registration_compulsory` etc.); the "Admission fee" field is relabelled **"Registration Fee"**. All new fields use `settings.get(...)` (they may be absent on an un-migrated project). Route passes `charge_config` = `get_charge_config(settings)`.
- **`shift_slots.html`** (new, ADR-65; UX-reworked ADR-68) — Settings › Shift Slots. Top: a **"Shift Timing Guide"** card looping `bucket_windows` (`describe_time_buckets()`) as four "start-time range → shift" tiles in **12-hour AM/PM** form using each row's `start_12h`/`end_12h` (5:00 AM – 12:00 PM → Morning, 12:00 PM – 4:00 PM → Afternoon, 4:00 PM – 9:00 PM → Evening, 9:00 PM – 5:00 AM → Night). Then an add/edit form whose primary fields are **Start time** / **End time** (`<input type=time>`) with two **read-only auto-filled** fields beside them — `#f_shift_display` (**Shift Category**, from the start time) and `#f_duration_display` (**Duration**, end − start) — plus hours label `<select>`, monthly fee, night-hourly switch + rate, sort order. The `time_bucket` `<select>` (unchanged name/options, "Auto" default) is collapsed inside `<details id="slotOverride">` ("Exceptional slot? Set the shift manually"), auto-opened on Edit only when a stored override exists. A live `#slot_preview` line ("Runs ~7h · Evening shift", "· set manually" when overridden) and the two read-only fields are recomputed on every start/end/bucket/night-switch change by JS that mirrors `resolve_slot_bucket`'s precedence via a `bucketWindows` blob (still the 24h `start`/`end`). Below, a table of configured slots (name, window, hours label **+ `· Xh`** from `span_hours`, fee, resolved shift + a "set manually" badge, active state) with per-row Edit (JS fills the form via a `data-slot` JSON attribute and swaps the form `action`) and an Enable/Disable POST form. The word "bucket" is not shown to the admin anywhere — it's "Shift" / "Shift Category". Modelled on `membership_settings.html`.
- **`library_profile.html`** (modified, ADR-67) — the Seating Capacity section gained a fourth input, `night_capacity`.
- **`index.html`** (modified) — a "Shift Slots" `action-card` tile added (now 8 cards total).
