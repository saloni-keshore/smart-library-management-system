# Changelog

Every coding session that changes behavior gets a new entry at the top, using this template:

```markdown
## YYYY-MM-DD — <short title>

- **Feature:** what capability this is part of
- **Files changed:** exact paths (not "various files") — code, templates, static, migrations
- **Why:** the actual motivation — a bug report, a design decision, a dependency, not just "improvement"
- **Database changes:** new/altered tables or columns, and which `migrate_*.py` script (if any) applies it to existing installs; "None" if not applicable
- **UI changes:** what a user visibly sees differently; "None" if not applicable
- **Future impact:** what this unblocks, what it constrains, what it leaves as debt — cross-link a [11_FUTURE_WORK.md](11_FUTURE_WORK.md) `TD-N`/`PF-N` id if this created or resolved one
```

Entries before 2026-07-20 are reconstructed from `git log` since no changelog existed at the time — fields marked *"Not recorded (predates changelog)"* genuinely can't be reconstructed with confidence; don't guess at them.

---

## 2026-07-21 — Data & Backup: removed redundant Export Database action

- **Feature:** Settings → Data & Backup
- **Files changed:** `routes/setting.py`, `templates/settings/data_backup.html`, `docs/05_ROUTES_REFERENCE.md`, `docs/06_TEMPLATES_REFERENCE.md`, `docs/10_FEATURE_MODULES.md`, `docs/FILE_REFERENCE.md`, `docs/WHERE_TO_MODIFY.md`, `docs/01_OVERVIEW.md`, `docs/11_FUTURE_WORK.md`, `docs/DECISIONS.md`
- **Why:** `Export Database` (`backup_export_db`, `GET /settings/backup/export-db`) and `Download Backup` (`backup_create`, `POST /settings/backup/create`) both handed the user the exact same `library.db` file — the only difference was that `backup_export_db` was a bare passthrough with no server-side trace, while `backup_create` also copied the file into `backups/` and called `record_backup()` to keep "Last Backup Date" accurate. Having two buttons for one output was confusing and let someone export via the untracked path and end up with a stale backup-date stat. Removed the untracked duplicate and kept the single action that already did the right thing, renamed for clarity.
- **Database changes:** None.
- **UI changes:** Data & Backup's "Manual Export & Backup" card now shows two actions instead of three: `Export CSV` (unchanged) and `Create Backup` (was `Download Backup` — same underlying behavior, copy → record → download). The button row layout changed from three `col-md-4` columns to two `col-md-6` columns.
- **Future impact:** Recorded ADR-10 in [DECISIONS.md](DECISIONS.md) (single tracked backup/export action, not a tracked+untracked pair) so a second raw-download route isn't reintroduced later. No `TD-N`/`PF-N` opened or resolved — PF-5 (no scheduled backups) still applies, its wording updated to reflect the two remaining actions.

## 2026-07-21 — Settings module completed: Notification Settings, Staff & User Access, Data & Backup, Security Settings

- **Feature:** Settings → Notification Settings (was a "coming soon" stub), plus three brand-new pages: Staff & User Access, Data & Backup, Security Settings. Also moved reminder-day/send-reminder ownership from Membership Settings to Notification Settings.
- **Files changed:** `database/migrate_notification_settings.py` (new), `database/notification_settings_queries.py` (new), `database/migrate_backup_log.py` (new), `database/backup_queries.py` (new), `database/migrate_security_settings.py` (new), `database/security_settings_queries.py` (new), `templates/settings/notification_settings.html` (new), `templates/settings/staff_access.html` (new), `templates/settings/data_backup.html` (new), `templates/settings/security_settings.html` (new), `database/schema.sql`, `database/membership_settings_queries.py`, `routes/setting.py`, `templates/settings/membership_settings.html`, `templates/settings/index.html`, `static/css/settings.css`, `static/js/settings.js`, `routes/dashboard.py`, `templates/dashboard/index.html`, `app.py`, `templates/components/notification_dropdown.html`
- **Why:** Notification Settings was the last remaining "coming soon" stub on the Settings landing page (PF-1's other half); this pass finishes it out and, while touching the Settings module, fills in the three cards (Staff & User Access, Data & Backup, Security Settings) that previously had no route/template at all. Reminder-day/send-reminder configuration also had two competing homes (`membership_settings` and the new notification columns) — consolidated to one owner (Notification Settings) instead of shipping both.
- **Database changes:** `library_settings` gained 19 columns (`reminder_7_days`, `reminder_3_days`, `reminder_1_day`, `notify_on_expiry_day`, `notify_after_expiry`, `notify_in_app`, `notify_sms`, `notify_email`, `notify_whatsapp`, `quiet_hours_enabled`, `quiet_hours_start`, `quiet_hours_end`, `quiet_hours_allow_critical`, `dash_show_badge_count`, `dash_show_expiry_today`, `dash_show_expiry_tomorrow`, `dash_show_overdue`, `dash_show_pending_fees`, `dash_show_new_admissions`) via `database/migrate_notification_settings.py` for existing installs and directly in `database/schema.sql` for fresh ones — same reused-row pattern as Receipt Settings (ADR-7), extended in ADR-8. Two brand-new tables: `backup_log` (one row per admin — `log_id`, `admin_id` UNIQUE, `last_backup_at`, `backup_filename`) via `database/migrate_backup_log.py`, and `security_settings` (one row per admin — `setting_id`, `admin_id` UNIQUE, `session_timeout_minutes`, `remember_me_enabled`, `login_notifications_enabled`, `created_at`/`updated_at`) via `database/migrate_security_settings.py` — both decoupled from `library_settings` on purpose (ADR-9). `membership_settings.reminder_days`/`send_reminders` columns are left in place (no `DROP COLUMN`) but `database/membership_settings_queries.py`'s `save_membership_settings()` no longer writes to them.
- **UI changes:** Notification Settings is now a full form page (Reminder Rules, Notification Channels with SMS/Email/WhatsApp marked "Integration coming soon", Quiet Hours with JS-driven enable/disable of the time inputs, Dashboard Notifications, a static Notification Preview card, and the same "Configuration Changes" diff table used by Membership/Receipt Settings). Staff & User Access is a "Coming Soon" placeholder explaining the single-admin limitation and previewing 4 future roles. Data & Backup shows DB size/last backup date/backup location plus Export Database, Export CSV, and Download Backup actions (the latter writes into the previously-empty `backups/` folder). Security Settings adds a working Change Password form (with client-side confirm-match validation) and a Session Preferences form (timeout, remember me, login notifications), plus a visual-only "Future Security Features" card (2FA, Device Management). Membership Settings' reminder-day/send-reminder inputs were replaced with a read-only summary sourced from Notification Settings, linking out to it. Settings landing page now has 7 clickable cards instead of 4. Dashboard's "Pending Fees" stat card is now conditionally shown per `dash_show_pending_fees`, and the navbar bell dropdown now respects `dash_show_badge_count`/`dash_show_expiry_today`/`dash_show_expiry_tomorrow`/`dash_show_overdue` toggles (defaulting to shown for anyone who hasn't touched Notification Settings yet).
- **Future impact:** Resolved [11_FUTURE_WORK.md](11_FUTURE_WORK.md) PF-1 in full (both the Receipt Settings and Notification Settings halves). Opened TD-23 (dead `membership_settings.reminder_days`/`send_reminders` columns), TD-24 (no SMS/Email/WhatsApp/quiet-hours dispatch engine exists — all of it is persisted preference only), TD-25 (`dash_show_new_admissions` has no widget to attach to yet), TD-26 (security preferences persisted but not enforced — no session-expiry middleware, no login-notification delivery). Opened PF-4 (Staff & User Access is a placeholder only) and PF-5 (no automatic/scheduled backups). Recorded ADR-8 (Notification Settings as the single owner of reminder/channel/quiet-hour/dashboard-display preferences) and ADR-9 (Data & Backup / Security Settings use dedicated tables instead of extending `library_settings`, specifically to avoid the Library-Profile-must-exist-first coupling) in [DECISIONS.md](DECISIONS.md).

## 2026-07-20 — Receipt Settings feature

- **Feature:** Settings → Receipt Settings
- **Files changed:** `database/receipt_settings_queries.py` (new), `database/migrate_receipt_settings.py` (new), `templates/settings/receipt_settings.html` (new), `routes/setting.py`, `static/js/settings.js`, `static/css/settings.css`, `database/schema.sql`
- **Why:** the Receipt Settings card on the Settings landing page linked to a "coming soon" stub; this replaces it with a working configuration page (numbering, branding print toggles, paper size, printing/email preferences, footer) so the Payments module has somewhere to read receipt preferences from later.
- **Database changes:** added 11 columns to the existing `library_settings` table — `receipt_prefix`, `next_receipt_number`, `auto_increment_receipt`, `print_logo`, `print_stamp`, `print_signature`, `paper_size`, `auto_print`, `auto_email`, `open_pdf_after_save`, `duplicate_copy` — via `database/migrate_receipt_settings.py` for existing installs (run manually against `database/library.db` in this session) and directly in `database/schema.sql` for fresh ones. No new table: receipt settings live on the same per-admin row as Library Profile, reusing `receipt_footer`.
- **UI changes:** Settings → Receipt Settings is now a full form page: receipt numbering with a live "next receipt" preview, read-only branding preview pulling logo/stamp/signature from Library Profile with print toggles, paper size + printing checkboxes, footer textarea, an email-preference checkbox (save-only, no emailing yet), a live-updating receipt preview card, and a "Configuration Changes" diff table after saving — mirroring the Membership Settings page's pattern.
- **Future impact:** opened [11_FUTURE_WORK.md](11_FUTURE_WORK.md) TD-22 — these settings are configuration only, same shape as TD-7; nothing yet reads them to actually generate/print/email a receipt. Resolved PF-1's Receipt Settings half (Notification Settings remains a stub). Recorded the "extend the existing row, update-only" approach as ADR-7 in [DECISIONS.md](DECISIONS.md).

## 2026-07-20 — Documentation system replaced and expanded

- **Feature:** Project documentation (`docs/`)
- **Files changed:** Removed all 20 old files (`docs/01_Requirement_Analysis.md` through `docs/20_Normalization.md`). Added `docs/README.md`, `01_OVERVIEW.md`–`11_FUTURE_WORK.md`, `FILE_REFERENCE.md`, `DIAGRAMS.md`, `CODE_JOURNEY.md`, `WHERE_TO_MODIFY.md`, `TROUBLESHOOTING.md`, `CHANGELOG.md`, `DECISIONS.md`. Added root `CLAUDE.md`.
- **Why:** the old docs described a project that didn't match reality (referenced a non-existent `ml/` folder, MySQL, Scikit-learn, ReportLab — none used anywhere; actual stack is Flask + SQLite + Jinja2 + Bootstrap + Chart.js + matplotlib) and were never updated as the app evolved. Replaced with a reference set verified against the actual source, then expanded per a follow-up request to add per-file dependency cards, Mermaid diagrams, a request-flow walkthrough, a "where to modify X" lookup, a troubleshooting guide, and a living technical-debt log.
- **Database changes:** None — documentation only.
- **UI changes:** None.
- **Future impact:** established the doc-maintenance policy now recorded in `CLAUDE.md` (every code change updates docs + this changelog in the same session) and a living `TD-N` technical-debt log in [11_FUTURE_WORK.md](11_FUTURE_WORK.md) (21 items opened from this pass, see that file). No code changed in this session — the debt items are documented, not yet fixed.

## 2026-07-20 — Membership Settings feature (commit `ef688b9`)

- **Feature:** Settings → Membership Settings
- **Files changed:** `database/membership_settings_queries.py` (new), `templates/settings/membership_settings.html` (new), `database/migrate_membership_setting.py`, `database/schema.sql`, `routes/setting.py`, `templates/settings/index.html`
- **Why:** first step toward making plan fees/durations configurable per library instead of hardcoded, ahead of wiring it into the actual membership create/renew flow.
- **Database changes:** added `membership_settings` table (one row per admin; monthly/quarterly/half-yearly/yearly fee+days, admission fee, late fee, renewal grace days, auto-expiry/early-renewal/reminder flags, reminder days) via `database/migrate_membership_setting.py` for existing installs, and directly in `database/schema.sql` for fresh ones.
- **UI changes:** Settings landing page's "Membership Settings" and "Receipt Settings" cards changed from disabled "Coming soon" placeholders to a live link (Membership Settings) and a stub link (Receipt Settings); added the Membership Settings form page with a "what changed" diff banner shown after saving.
- **Future impact:** opened [11_FUTURE_WORK.md](11_FUTURE_WORK.md) TD-7 — `routes/membership.py`'s `create()`/`renew()` do not yet read from this table, so configuring it currently has no effect on actual membership creation.

## 2026-07-06 — Refactor (commit `62bb7b0`)

- **Feature:** Codebase-wide
- **Files changed:** Not recorded (predates changelog) — see `git show 62bb7b0` for the diff.
- **Why:** commit message states "Refactor code structure for improved readability and maintainability"; no further detail recorded.
- **Database changes:** Not recorded (predates changelog).
- **UI changes:** Not recorded (predates changelog).
- **Future impact:** Not recorded (predates changelog).

## 2026-07-06 — Settings uploads scaffolding (commit `fdcb80c`)

- **Feature:** Settings → Library Profile (uploads)
- **Files changed:** `static/uploads/settings/.gitkeep`
- **Why:** track the (then-empty) upload directory in git ahead of the Library Profile logo/stamp/signature upload feature.
- **Database changes:** None.
- **UI changes:** None.
- **Future impact:** enabled `routes/setting.py`'s `_save_upload()` to have a tracked destination directory.

## 2026-07-05 — Cashbook analytics and transaction management (commit `5b482dd`)

- **Feature:** Cashbook
- **Files changed:** `database/cashbook_queries.py` (new), `database/audit_queries.py` (new), `database/cashbook_categories.py` (new), `routes/cashbook.py`, `templates/cashbook/*`, `templates/components/cashbook_*.html`
- **Why:** build out a full manual ledger with filtering/search/pagination, category/payment-method breakdowns, and an audit trail for changes.
- **Database changes:** established `cashbook` as the central ledger table (extending the base table from `schema.sql` with `category`/`person`/`admin_id`/`payment_method` via earlier `ALTER TABLE`s) and added `audit_log` (`database/migrate_audit_log.py`).
- **UI changes:** new Cashbook page with summary cards, filters, charts, transaction list, and activity/audit log.
- **Future impact:** established ADR-3 and ADR-4 (see [DECISIONS.md](DECISIONS.md)) — Cashbook as the single source of truth for the ledger, and auto-generated entries being read-only in the UI.

## 2026-07-03 to 2026-07-04 — Membership Distribution feature (commits `583931f`, `d67daa5`)

- **Feature:** Membership Distribution
- **Files changed:** `routes/membership_distribution.py` (new), `utils/charts.py` (`generate_membership_distribution_donut` added), `templates/memberships/distribution.html` (new), `templates/components/membership_*.html` (new)
- **Why:** give admins a plan-distribution analytics view (counts/percentages per plan, active/expired totals, quick insights).
- **Database changes:** None (reads existing `memberships`/`students`/`payments`).
- **UI changes:** new Membership Distribution page, linked from the Dashboard's membership chart card.
- **Future impact:** established the server-rendered matplotlib chart pattern (ADR-5 in [DECISIONS.md](DECISIONS.md)) that later coexisted with the client-side Chart.js approach used by Cashbook/BI.

## 2026-07-02 — Dashboard UI enhancements (commit `c807844`)

- **Feature:** Dashboard
- **Files changed:** Not recorded in detail (predates changelog) — commit message: "Enhance dashboard UI with new components and improved styles."
- **Why:** Not recorded (predates changelog).
- **Database changes:** None recorded.
- **UI changes:** Dashboard visual/component improvements (exact scope not recorded).
- **Future impact:** Not recorded (predates changelog).

## 2026-07-01 — Multi-tenant `admin_id` isolation (commit `90b65e3`)

- **Feature:** Core architecture (multi-tenancy)
- **Files changed:** `database/migrate.py` (new), `database/schema.sql`, plus routes/templates touching `enquiries`/`students` (not individually recorded)
- **Why:** retrofit per-admin data isolation onto what was previously a single-tenant app.
- **Database changes:** added `admin_id` to `enquiries`; recreated `students` with `admin_id` + `UNIQUE(mobile, admin_id)`, backfilling existing rows to the first admin found.
- **UI changes:** None directly (backend isolation change).
- **Future impact:** established ADR-2 (see [DECISIONS.md](DECISIONS.md)) — the manual, per-query `admin_id` filtering convention that every feature built afterward depends on, and the inconsistency it left behind (some tables retrofitted without FK support — TD-2/TD-3/TD-5 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)).

## 2026-06-30 — V1 buildout and config management (commits `d13f945`, `615df85`)

- **Feature:** Core architecture, Membership, Payment
- **Files changed:** `config.py` (new, subsequently never wired into `app.py`), membership/payment routes and templates (not individually recorded)
- **Why:** initial working version ("bulding V1").
- **Database changes:** Not recorded in detail (predates changelog).
- **UI changes:** Not recorded in detail (predates changelog).
- **Future impact:** `config.py` became dead code (TD-9 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)) — never revisited after this commit.

## 2026-06-28 — Initial project setup (commits `1404bcb`, `f4d72f4`)

- **Feature:** Core architecture
- **Files changed:** `app.py`, initial `database/` module (not individually recorded)
- **Why:** Day 1/Day 2 project scaffold.
- **Database changes:** Initial schema (exact original shape not recorded — `schema.sql` has since evolved through 6 commits, see [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md)).
- **UI changes:** Not recorded (predates changelog).
- **Future impact:** established the Flask-factory + blueprint-registration pattern (`app.py`) still in use today.
