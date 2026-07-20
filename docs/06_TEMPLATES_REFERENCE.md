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

**`navbar.html`** — plain include (not block-based). Expects `session['username']` (defaults `"Admin"` in the template). Includes `components/notification_dropdown.html`. Search box is static/non-functional. Links to `setting.index` and `auth.logout`. Inline script fills `#currentDate` client-side.

**`sidebar.html`** — left nav. Local Jinja macro `nav_badge(count)` renders a red badge if `count > 0`. Expects `enquiries_new_count`, `students_new_today_count`, `memberships_expiring_soon_count`, `payments_pending_count` — **note:** no route or context processor currently supplies these variables (only `sidebar.html` references them), so the badges likely render blank/undefined in practice. Active-link highlighting is done inline per-link via `request.endpoint.startswith('student.')`-style checks, not a passed-in "active" flag.

## `templates/components/` (~45 shared partials)

**Generic primitives**, used via `{% include %}` with `with`, or `{% call %}` macros:
| File | Purpose |
|---|---|
| `stat_card.html` | KPI tile — icon, title, value, trend line. Params: `title, value, icon, trend, trend_color, trend_icon, col_class, accent_class` |
| `chart_card.html` | Card wrapper with header + `{{ caller() }}` body slot |
| `table_card.html` | Same caller-based wrapper, styled for tables |
| `activity_card.html` | Card meant to be `{% extends %}`-ed (has a `{% block activity %}`), not included |
| `alert.html` | **Empty file (0 bytes)** — unused placeholder |
| `dashboard_header.html`, `insights_card.html`, `quick_actions.html` | Dashboard-specific: header banner, shortcut action row |
| `notification_dropdown.html` | Navbar bell — expects `nav_notifications` (from `app.py`'s context processor) with `.counts`/`.buckets`/`.meta` |
| `revenue_chart.html`, `payment_chart.html`, `membership_chart.html`, `membership_distribution_chart.html` | Dashboard cards displaying **pre-rendered PNGs** from `static/charts/`, wrapped in a skeleton loader (`data-chart-stage`, revealed by `dashboard-charts.js`) |
| `expiry_table.html`, `upcoming_expiry.html`, `recent_admissions.html` | Dashboard mini-tables |
| `add_transaction_modal.html`, `edit_transaction_modal.html`, `transaction_details_modal.html` | Bootstrap modals shared by Cashbook + Dashboard quick actions, driven by `static/js/transaction_modal.js` |

**Business Intelligence (`bi_*`, 9 files)** — data from `database/bi_queries.py` via `routes/business_intelligence.py`:
| File | Purpose |
|---|---|
| `bi_health_score.html` | Circular Chart.js gauge for the composite health score/status |
| `bi_advisor.html` | Intentional "Coming Soon" placeholder — reserved for a future AI-advisor feature |
| `bi_action_center.html` | Loops `action_items` into recommendation tiles |
| `bi_health_status.html` | Compact status readout paired with the health score |
| `bi_membership_growth_chart.html`, `bi_revenue_growth.html`, `bi_revenue_trend_chart.html` | Chart.js canvas cards for growth/trend metrics |
| `bi_timeline.html` | Chronological activity feed |
| `bi_top_expense.html`, `bi_top_revenue.html` | Ranked top-category list cards |

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
| `enquiries/` | `index.html`, `add.html`, `edit.html`, `view.html` |
| `students/` | `index.html`, `admission.html`, `view.html`, `edit.html` |
| `memberships/` | `index.html`, `create.html`, `renew.html`, `distribution.html`, `analytics.html` |
| `payments/` | `index.html`, `collect.html`, `create.html`, `success.html` — note `create.html`/`success.html` exist but no current route in `routes/payment.py` renders them (only `index`/`collect` are wired up) |
| `cashbook/` | `index.html`, `transactions.html`, `analytics.html` — only `index.html` is rendered by `routes/cashbook.py`; `transactions.html`/`analytics.html` appear to be leftover/unwired |
| `business_intelligence/` | `index.html` |
| `notification/` | `index.html` |
| `settings/` | `index.html`, `library_profile.html`, `membership_settings.html` — note `routes/setting.py`'s `receipt_settings`/`notification_settings` have no corresponding templates yet |
| `reports/` | `index.html` — unreferenced (see `routes/report.py`, a pure redirect shim) |

See [11_FUTURE_WORK.md](11_FUTURE_WORK.md) for the unwired-template list.
