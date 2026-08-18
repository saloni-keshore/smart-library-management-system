# Static Assets

No build step — all CSS/JS is hand-authored and served directly via `url_for('static', ...)`. Base framework is Bootstrap 5.3.7 + Bootstrap Icons 1.11.3, both loaded from CDN in `templates/layouts/base.html` / `auth_base.html` (not vendored locally).

## `static/css/`

| File | Lines | Scope |
|---|---|---|
| `style.css` | 1312 | Main global stylesheet — layout, navbar, sidebar, base component styles. Scopes sidebar theme variables to `.sidebar-wrapper` rather than a global `:root`: `--sidebar-bg:#1a2234`, `--sidebar-active-bg:#2563eb`, `--sidebar-logo-green:#22c55e`, `--sidebar-danger:#ef4444` |
| `business_intelligence.css` | 723 | BI dashboard page. Own `:root` tokens prefixed `--bi-*` |
| `ai_center.css` | 756 | AI Center's Student Risk Analysis + Settings pages. Own `.ai-center-page`-scoped tokens prefixed `--ai-*`, same isolation pattern as `business_intelligence.css`. As of 2026-07-27 (Settings page UX pass) also styles the Settings page's info banner, inline `.ai-info-tip` help popovers, the risk-range segmented bar and the weight-influence bars |
| `cashbook.css` | 323 | Cashbook page |
| `membership_distribution.css` | 992 | Membership Distribution page. Own `:root` tokens prefixed `--md-*` |
| `settings.css` | 299 | Settings pages, incl. the Receipt Settings live-preview card, the Notification Settings preview card (`.settings-notif-preview`), and the "Coming Soon" placeholder styles shared by Staff & User Access / Security Settings (`.settings-coming-soon-badge`, `.settings-coming-soon-icon`, `.settings-role-card`) |
| `login.css` | 75 | Auth pages (`auth_base.html`). Sets `font-family: 'Poppins', sans-serif` |
| `panda.css` | 431 | Panda AI Assistant floating widget (added 2026-07-27, ADR-43) — loaded globally from `layouts/base.html` (not page-specific, unlike every other file in this table). Own `:root` tokens prefixed `--panda-*`, same isolation pattern as `--ai-*`/`--bi-*`/`--md-*` |
| `navbar_search.css` | 79 | Global navbar search dropdown (added 2026-08-17, ADR-44) — loaded globally from `layouts/base.html` (not page-specific), same reasoning as `panda.css`. Unlike `--ai-*`/`--bi-*`/`--md-*`/`--panda-*`, deliberately **unscoped** — `.navbar-search` is already the unique root since `navbar.html` only ever renders once per page, so no page-scoping prefix is needed |

**Color tokens actually in use** (from `--bi-*`/`--md-*` variables, consistent across both files): primary `#2563eb`, success `#16a34a`, warning `#f59e0b`, danger `#ef4444`, info `#06b6d4`, violet `#7c3aed`, plus soft bg/text tint pairs and neutral tones `#0f172a` (ink), `#64748b` (muted), `#eef2f7` (border), `#f8fafc` (bg). This is the real, current palette — treat it as authoritative over any older design-intent documents.

Each page-specific stylesheet defines its **own** `:root` tokens rather than sharing one global design-tokens file — if you change a color, you currently have to update it in every file that redefines it.

## `static/js/`

| File | Lines | Purpose |
|---|---|---|
| `business_intelligence.js` | 161 | Reads `window.biChartData`, renders BI dashboard Chart.js charts (health gauge, growth/trend), with empty-state handling |
| `ai_center_search.js` | 133 | Student Risk Analysis's autocomplete search box (ADR-41) — debounces input, fetches `routes/ai_center.py`'s `student_suggestions()` JSON endpoint, renders/keyboard-navigates the dropdown, and navigates to `?student_id=` only on an explicit click/Enter selection |
| `ai_center_settings.js` | 114 | Settings page, cosmetic only (added 2026-07-27, Settings page UX pass). Opens/closes the `.ai-info-tip` help popovers on hover, tap or keyboard focus; live-redraws the risk-range bar and the three weight bars (plus their running Total) as the number inputs change. Never validates — `_parse_settings_form()` in `routes/ai_center.py` is still the only place the weights-sum-to-100/threshold-ordering rules are enforced, this file just previews what the saved values would look like |
| `cashbook.js` | 212 | Reads `window.cashbookChartData`, renders income/expense/revenue-source/payment-method charts; transaction-modal logic factored out into `transaction_modal.js` |
| `dashboard-charts.js` | 53 | Generic skeleton-loader controller — reveals `[data-chart-stage]` elements after each element's own `data-reveal-delay` (ms), by toggling an `is-loaded` class that CSS (`static/css/style.css`) crossfades between `.chart-skeleton`/`.chart-content`; exposes `window.revealDashboardChart()` (still unused - no chart-rendering code calls it, PNGs are server-rendered before the page ships). Shared across Dashboard (revenue + membership charts) and Membership Distribution (donut chart) - any page including this file gets per-chart-stage reveal automatically. Until 2026-07-21 there was a second, redundant `DOMContentLoaded` handler here that unconditionally revealed every `.chart-stage` at a hard-coded 1200ms via inline styles/`d-none`, silently overriding each element's own `data-reveal-delay` (900ms for two of the three chart cards) - removed as dead/conflicting logic once `revenue_chart.html`'s stray `d-none` (the only thing that second handler was actually still needed for) was also removed; see [CHANGELOG.md](CHANGELOG.md). As of 2026-08-18, also defines `initRevenuePeriodSelect()`: listens for `change` on `#revenue-period-select` (Revenue Overview card's "This Year"/"Last Year" dropdown, `templates/components/revenue_chart.html`), `fetch()`s `GET /dashboard/revenue-chart?period=<value>` (`routes/dashboard.py`'s `revenue_chart()`), and sets `#revenue-chart-img`'s `src` to the cache-busted `image_url` in the JSON response - no skeleton re-trigger, the image just swaps in place. |
| `login.js` | 19 | Password show/hide toggle on the login page |
| `panda.js` | 300 | Panda AI Assistant floating widget (added 2026-07-27, ADR-43) — loaded globally from `layouts/base.html` for a logged-in session only (not page-specific, unlike every other file in this table). Opens/closes/minimizes the slide-out panel; fetches `panda/routes.py`'s insights/suggested-questions/conversations JSON endpoints; renders chat bubbles and the chat-history overlay; sends messages via `fetch()` with the same `X-CSRF-Token` header pattern `settings.js` uses. Lazily creates a conversation (`POST /panda/conversations`) only on the first message actually sent, not on panel open, so opening the widget never creates an empty conversation |
| `navbar_search.js` | 189 | Global navbar search (added 2026-08-17, ADR-44) — loaded globally from `layouts/base.html` for a logged-in session only, same gating as `panda.js`. A structural extension of `ai_center_search.js`'s pattern to four entity types at once: debounces input, fetches `routes/search.py`'s `suggestions()` JSON endpoint, renders a dropdown grouped by type (Students/Payments/Enquiries/Cashbook headers), keyboard-navigates the flattened list, and navigates to that record's real page only on an explicit click/Enter selection — Cashbook rows are rendered but not clickable (no single-entry view page exists yet, TD-56), so `selectItem()` no-ops for that group |
| `membership_distribution.js` | 144 | Animated bars/table interactions for the distribution page |
| `settings.js` | 455 | Library Profile form validation, toast notifications, file upload preview (`libraryProfileForm`); Receipt Settings live preview — receipt number, logo/stamp/signature toggles, paper size (`receiptSettingsForm`); Notification Settings quiet-hours enable/disable of the start/end time inputs (`notificationSettingsForm`); Security Settings new/confirm password match validation (`securityPasswordForm`) — each block guarded by its own form-presence check |
| `transaction_modal.js` | 116 | Shared Add/Edit Transaction modal logic (category toggling by type, person label swap, submit guard) — reused by Cashbook and Dashboard quick actions |

## `static/charts/` — server-generated PNGs

All three are regenerated **in place** (same filename overwritten, not versioned/timestamped) by `utils/charts.py`, only when a route that calls the corresponding generator function actually runs:

| File | Generated by | Shown on |
|---|---|---|
| `revenue.png` | `generate_revenue_chart(admin_id)` | Dashboard (`components/revenue_chart.html`) |
| `membership.png` | `generate_membership_chart(admin_id)` | Dashboard (`components/membership_chart.html`) |
| `membership_distribution_donut.png` | `generate_membership_distribution_donut(admin_id)` | Membership Distribution page |

Because these are shared files (not per-admin), **the last admin whose dashboard loaded is whichever chart image every other admin also sees until they load their own dashboard** — there is no per-admin chart file naming. This is a real cross-tenant leak in a multi-tenant app and is flagged in [11_FUTURE_WORK.md](11_FUTURE_WORK.md).

## `static/uploads/`

Only `static/uploads/settings/` exists (plus a `.gitkeep`). Files are named `{asset_type}_{admin_id}_{original_filename}` (e.g. `logo_1_Screenshot_2026-07-06_134639.png`), correctly namespaced per admin, uploaded via `routes/setting.py`'s `library_profile()` → `_save_upload()`.

## `static/images/`

Empty directory, no files.
