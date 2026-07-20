# Future Work, Known Technical Debt, and Stubs

This file has two distinct kinds of content — don't conflate them:

- **Known Technical Debt** — real defects/inconsistencies already in the codebase today. This is a **living log**: add a new `TD-N` row the moment you find a new one (during any coding session, not just a dedicated audit), and flip its `Status` to `Resolved` (don't delete the row) once it's fixed, with a note pointing at the [CHANGELOG.md](CHANGELOG.md) entry that fixed it.
- **Stub Routes & Planned Features** — intentionally incomplete work (flash-a-message placeholders, empty-context pages) that isn't a bug, just unfinished.

Everything below was discovered by reading the actual code (verified 2026-07-20), not inferred.

## Known Technical Debt

| ID | Issue | Severity | Location | Found On | Status |
|---|---|---|---|---|---|
| TD-1 | Chart PNGs written to shared, non-admin-scoped filenames — one admin can briefly see another's chart data | Medium (real cross-tenant data leak, low likelihood window) | `utils/charts.py` | 2026-07-20 | Open |
| TD-2 | `transactions` table defined twice with incompatible shapes (`schema.sql` vs `migrate_transactions.py`) | Medium (latent — table unused today, but a landmine for whoever wires it up) | `database/schema.sql`, `database/migrate_transactions.py` | 2026-07-20 | Open |
| TD-3 | `expenses` table exists but nothing reads or writes it | Low | `database/schema.sql` | 2026-07-20 | Open |
| TD-4 | Legacy `settings` table (non-admin-scoped) superseded by `library_settings` but still created | Low | `database/schema.sql` | 2026-07-20 | Open |
| TD-5 | `PRAGMA foreign_keys = ON` only runs once at schema-init; regular request connections never enforce FKs | Medium | `database/db.py`, `database/schema.sql` | 2026-07-20 | Open |
| TD-6 | `membership_status` never auto-flips to `'Expired'` on `end_date` passing — "effective status" recomputed independently in 3+ files | Medium (duplication risk — the 3 copies could drift) | `routes/dashboard.py`, `routes/student.py`, `routes/membership_distribution.py` | 2026-07-20 | Open |
| TD-7 | `membership_settings` (plan pricing/policy) configured via Settings but not read by Membership create/renew | Medium (feature gap, not a bug) | `routes/membership.py`, `database/membership_settings_queries.py` | 2026-07-20 (introduced alongside the 2026-07-20 Membership Settings feature) | Open |
| TD-8 | `requirements.txt` missing `matplotlib`/`numpy`, which `utils/charts.py` imports | High (breaks a fresh install immediately) | `requirements.txt`, `utils/charts.py` | 2026-07-20 | Open |
| TD-9 | `config.py`'s `Config`/`DevelopmentConfig`/`ProductionConfig` never imported by `app.py` | Low (dead code, mildly confusing) | `config.py`, `app.py` | 2026-07-20 | Open |
| TD-10 | `database/seed.py` doesn't seed data (name is misleading) and imports `generate_password_hash` unused | Low | `database/seed.py` | 2026-07-20 | Open |
| TD-11 | Unwired templates rendered by no route: `payments/create.html`, `payments/success.html`, `cashbook/transactions.html`, `cashbook/analytics.html`, `reports/index.html` | Low | see [FILE_REFERENCE.md](FILE_REFERENCE.md) template cards | 2026-07-20 | Open |
| TD-12 | `templates/components/alert.html` is a 0-byte empty file | Low | `templates/components/alert.html` | 2026-07-20 | Open |
| TD-13 | `routes/auth.py` hardcodes `role="Admin"` on registration; schema default is lowercase `'admin'` | Low (bites the first case-sensitive `role` check) | `routes/auth.py`, `database/schema.sql` | 2026-07-20 | Open |
| TD-14 | `routes/enquiries.py`'s `delete()` runs on a plain `GET`, no confirmation | Medium (accidental/crawler-triggered deletion risk) | `routes/enquiries.py` | 2026-07-20 | Open |
| TD-15 | `templates/layouts/sidebar.html` expects badge-count context vars (`enquiries_new_count`, etc.) that nothing supplies | Low (cosmetic — badges render blank) | `templates/layouts/sidebar.html` | 2026-07-20 | Open |
| TD-16 | Six folders are completely empty with zero references anywhere: `models/`, `services/`, `reports/`, `tests/`, `backups/`, `.agents/` | See TD-20 for `tests/` specifically | project root | 2026-07-20 | Open |
| TD-17 | No `.gitignore`; 38 `.pyc` files committed to git, producing noisy binary diffs | Low (hygiene) | repo root, `__pycache__/` dirs | 2026-07-20 | Open |
| TD-18 | Root `README.md` is empty (0 bytes) | Low | `README.md` | 2026-07-20 | Open |
| TD-19 | `if "admin_id" not in session: return redirect("/")` duplicated in nearly every route function instead of centralized | Medium (easy to forget on a new route, silently exposing it) | every `routes/*.py` except `report.py`/`membership_analytics.py` | 2026-07-20 | Open |
| TD-20 | No automated tests exist at all (`tests/` empty) | High (highest-leverage gap — fee/receipt/health-score logic has no regression safety net) | `tests/` | 2026-07-20 | Open |
| TD-21 | `database/migrate_*.py` scripts import via bare `from db import get_connection` instead of `from database.db import get_connection` — only works because they're always run standalone | Low (fragile if ever imported as a module instead of run as a script) | every `database/migrate_*.py` | 2026-07-20 | Open |

## Stub Routes & Planned Features

Not defects — intentionally incomplete, called out so nobody mistakes "coming soon" for a bug.

| ID | What | Where |
|---|---|---|
| PF-1 | Receipt Settings and Notification Settings both just flash "coming soon" and redirect — no templates or query modules exist yet | `routes/setting.py`'s `receipt_settings()`, `notification_settings()` |
| PF-2 | Membership Analytics renders a template with zero query/context — likely superseded by the (fully implemented) Membership Distribution page | `routes/membership_analytics.py` |
| PF-3 | Reports permanently redirects to Business Intelligence — kept only as a URL-compatibility shim | `routes/report.py` |

## Next logical slices (recommendations, not commitments)

1. Wire `membership_settings` (TD-7) into `routes/membership.py`'s `create()`/`renew()` — the most natural next step given how recently the settings side was built.
2. Fix TD-8 (`requirements.txt`) — takes one line, unblocks every fresh install.
3. Add a first test around `database/bi_queries.py`'s `get_business_health_score` and `database/cashbook_queries.py`'s aggregate functions (TD-20) — these are the highest-value, least-tested business logic in the app.
4. Decide PF-1's scope (Receipt Settings / Notification Settings) or explicitly deprioritize and remove the nav entries so they stop looking unfinished to end users.
