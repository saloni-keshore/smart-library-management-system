# Code Journey — How a Request Actually Flows

The general shape (see [DIAGRAMS.md](DIAGRAMS.md) diagram 3 for the visual): **Browser → Blueprint route function → (raw SQL or a `database/*_queries.py` module) → SQLite → Jinja template (extends a layout, includes components) → back to the browser.** Every step below is traced against real file/function names so you can jump straight to the code.

## Journey 1 — Collecting a membership payment (a write path)

This is the most important flow in the app: it touches three tables in one transaction and is the pattern every other "record some money" feature follows.

1. **Browser** submits the form on `templates/payments/collect.html` → `POST /payments/collect/<membership_id>`.
2. **Route** `routes/payment.py`'s `collect(membership_id)` receives it:
   - Checks `if "admin_id" not in session: return redirect("/")`.
   - Opens a connection via `database.db.get_connection()`.
   - Verifies the membership belongs to the current admin (`memberships` joined to `students` on `admin_id`) — if not found, flashes and redirects to `student.index`.
   - Validates `amount_paid`: must parse as a number, be `> 0`, and be `<= pending_amount`. Any failure flashes a `danger` message and re-renders `payments/collect.html`.
3. **Write #1** — generates a receipt number `REC-YYYYMMDD-<membership_id>-<new_paid>` and `INSERT`s into `payments`.
4. **Write #2** — updates `memberships.paid_amount` / `memberships.pending_amount` on the same connection.
5. **Write #3** — calls `database/cashbook_queries.py`'s `insert_income_entry(conn, admin_id, category="Membership Fee", ...)`, passing the **same** connection/cursor so this write is part of the same transaction as writes #1 and #2.
   - Inside `insert_income_entry`: generates a `reference_id` via `_generate_reference_id`, `INSERT`s into `cashbook` with `source="Payments"` (not `"Cashbook Manual Entry"` — see below), then calls `database/audit_queries.py`'s `log_entry(cursor, admin_id, entry_id, "Auto-Created", ...)` — the audit row for **write #4**.
6. **Commit** happens once, after all four writes — if any step raised an exception first, nothing commits (SQLite's default transaction behavior on an open connection).
7. **Redirect** to `student.view` with a success flash — POST/Redirect/GET, so refreshing the result page doesn't resubmit the payment.
8. **Downstream read-side effects**, visible immediately on next page load without any extra code: the new `cashbook` row now appears in `routes/cashbook.py`'s ledger (as a **non-editable** row, since its `source` isn't `"Cashbook Manual Entry"` — see ADR-4 in [DECISIONS.md](DECISIONS.md)); it also feeds every aggregate in `database/bi_queries.py` (health score, revenue growth, top revenue sources) the next time `routes/business_intelligence.py`'s `index()` runs.

**Files touched, in order:** `templates/payments/collect.html` → `routes/payment.py` → `database/db.py` (raw SQL for payments/memberships) → `database/cashbook_queries.py` (`insert_income_entry`, `_generate_reference_id`) → `database/audit_queries.py` (`log_entry`) → back to `routes/payment.py` → `templates/students/view.html` (via redirect).

## Journey 2 — Viewing the Dashboard (a read + side-effect path)

1. **Browser** navigates to `GET /dashboard`.
2. **Route** `routes/dashboard.py`'s `dashboard()`:
   - Session check, same pattern as above.
   - Runs several raw SQL queries directly (no query module) against `students`, `memberships`, `payments`, `enquiries` — active/expired counts, revenue totals, upcoming expiries (`julianday` diff for `days_left`), recent admissions.
   - **Side effect:** calls `utils.charts.generate_revenue_chart(admin_id)` and `generate_membership_chart(admin_id)`. Each of these opens its **own** connection (via `database.db.get_connection()`, independent of the route's own connection), runs its own aggregation query, and overwrites `static/charts/revenue.png` / `static/charts/membership.png` in place.
3. **Template** `templates/dashboard/index.html` extends `layouts/base.html`, includes `components/{dashboard_header, quick_actions, revenue_chart, membership_chart, expiry_table, recent_admissions}.html`. The chart components don't receive chart data through the render context at all — they just `<img>` the static PNG path that step 2's side effect already wrote to disk.
4. **Global context processor** — before the template even starts rendering, `app.py`'s `inject_notification_summary` has already run (registered via `@app.context_processor`, fires on every render call, not just this route) and called `routes/notification.py`'s `get_notification_summary(admin_id)`, populating `nav_notifications` for `components/notification_dropdown.html` inside `navbar.html`.
5. **Browser** receives HTML referencing the just-regenerated PNGs — if two admins' dashboard loads interleave, there's a brief window where one admin could see the other's chart (see [11_FUTURE_WORK.md](11_FUTURE_WORK.md) TD-1).

**Files touched:** `routes/dashboard.py` → `database/db.py` (raw SQL) + `utils/charts.py` (own DB queries + file write) → `templates/dashboard/index.html` + 6 component templates → (in parallel) `app.py`'s context processor → `routes/notification.py` → `components/notification_dropdown.html`.

## The general pattern to follow for a new feature

1. Add a route function in the right `routes/*.py` (or a new blueprint, registered in `app.py`).
2. Start the function with the standard session guard (`if "admin_id" not in session: return redirect("/")`) — there's no decorator for this yet, copy the exact snippet used elsewhere.
3. For data access: if a `database/*_queries.py` module already exists for this feature (cashbook, BI, settings, membership settings), add a function there instead of writing raw SQL in the route — that's the pattern the more recently built features (Cashbook, BI, Settings) follow. Older features (dashboard, students, enquiries, notifications) still use raw SQL inline; don't feel obligated to match that older style for new code. `auth` is a special case as of 2026-07-23: it queries Supabase directly (`database/supabase_client.py`), not SQLite — see ADR-16 in [DECISIONS.md](DECISIONS.md) before touching it, since it's mid-migration and the rest of the app is not. `setting.py`'s `security_settings()` password branch picked up this same Supabase-direct pattern the same day (ADR-17) — its `admins.password` calls are inline `get_supabase_client()` calls, not a `database/*_queries.py` function, while every other function in `setting.py` still follows the query-module pattern.
4. Always filter by `admin_id` (directly, or via a join to a table that has it) — there is no framework-level tenant isolation, it's a manual convention (see ADR-2 in [DECISIONS.md](DECISIONS.md)).
5. If the new write should show up in the financial ledger, call `database/cashbook_queries.py`'s `insert_income_entry(conn, ...)` with the **same connection/cursor** as your other writes so it's part of one transaction, and pick a `source` value other than `"Cashbook Manual Entry"` so it's correctly treated as auto-generated/read-only in the Cashbook UI.
6. Render a template that extends `layouts/base.html`, reusing `components/stat_card.html` / `chart_card.html` / `table_card.html` for common layout shapes before hand-rolling new markup.
7. Update the relevant doc(s) in `docs/` and add a [CHANGELOG.md](CHANGELOG.md) entry in the same session — see the maintenance policy in [README.md](README.md).
