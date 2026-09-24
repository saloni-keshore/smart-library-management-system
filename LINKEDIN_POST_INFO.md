# Smart Library App — Info for a LinkedIn Post

A dump of everything factual about the project, so you can pull quotes/points for a post.
Everything below is verifiable against the actual codebase (see `docs/`).

---

## One-line description

A multi-tenant Flask web app that runs the back office of a coaching-center / reading-library
business — student enquiries, admissions, membership plans, fee collection, a cashbook ledger,
and a business-intelligence dashboard on top of that financial data.

## What it does (feature areas)

| Area | What it covers |
|---|---|
| Auth | Login / register / forgot-password, session-based |
| Dashboard | KPIs, revenue & membership charts, quick actions, expiry table, recent admissions |
| Enquiries | Full CRUD on prospective students |
| Students / Admissions | Convert an enquiry into a student, forced straight into a membership |
| Memberships | Create & renew, time-window shift slots, extra charges, refundable deposits |
| Membership Distribution | Plan-mix analytics (doughnut chart + table + insights) |
| Payments | Standalone fee collection against a membership's pending balance |
| Cashbook | Income/expense ledger, manual entries, category rules, audit log |
| Business Intelligence | Health score, growth trend, top revenue sources, ranked action items |
| Notifications | Membership-expiry buckets — full page + navbar bell on every page |
| Settings | 7 sub-pages: Library Profile, Membership Settings, Shift Slots, Receipt Settings, Notification Settings, Data & Backup, Security Settings |
| Panda ("Smart Business Assistant") | Floating chat widget, persisted multi-conversation history, rule/keyword-based replies computed from the admin's real data |

## The core money flow (the interesting bit for engineers)

Enquiry → Admission → Membership (create/renew) → Payment → Cashbook entry → BI aggregates.
One cross-cutting write path, source-of-truth-first: the membership row is written first, then the
payment, then a best-effort cashbook + audit-log entry — with explicit compensating rollback
(delete the membership, restore prior state) if the payment insert fails.

## Multi-tenancy

- One `admins` row = one library owner = one tenant.
- Session holds `admin_id`; every route checks it before doing anything.
- Isolation is enforced query-by-query with a `WHERE admin_id = ?` filter (or a join back to a
  table that has one) — a deliberate manual convention, no framework-level RLS.

## Tech stack (as actually installed)

- **Backend:** Flask (blueprint-per-feature), Jinja2 templates, no ORM
- **Database:** Supabase (PostgreSQL) via the `supabase-py` PostgREST client — `.eq()`/`.in_()`
  filtered queries in `database/*_queries.py` modules. Hand-maintained SQL schema, no migration runner.
- **Frontend:** Bootstrap 5.3, Bootstrap Icons, Chart.js 4.4 (all charts render client-side),
  Google Fonts "Poppins". Hand-authored CSS/JS, no build step.
- **Deploy:** runs on a read-only serverless filesystem (Render / Vercel configs in repo);
  chart payloads are built server-side and drawn in the browser — no server-side image generation.

## Notable engineering history

- **Incremental DB migration:** started on SQLite, migrated to Supabase **table by table**
  (~15 ADRs, one table per slice, each with a temporary dual-write mirror and a tracked
  removal condition) rather than a big-bang cutover. SQLite was fully removed only once the
  last table landed.
- **Docs-as-code:** `docs/` is treated as part of the codebase — a per-file reference, Mermaid
  diagrams, a changelog with a fixed 6-field template, an ADR log, and a living technical-debt
  register (`TD-1…`). Drift between docs and source is treated as a bug.
- **No AI overclaiming:** the assistant is explicitly named "Smart Business Assistant," not "AI
  Assistant." Replies are fixed templates + real numbers from a keyword intent classifier;
  the "forecast" is a plain linear trend extrapolation. No ML model and no LLM are wired in —
  and the docs say so plainly.

## Honest current limitations (don't post these, but know them)

- No row-level security — tenant isolation depends on every query remembering its filter.
- Several Settings toggles persist but aren't enforced yet (session timeout, quiet hours).
- No SMS/Email/WhatsApp dispatch; receipts are configuration-only (nothing prints/emails one).
- Membership Analytics route is a stub; Staff & User Access is a "Coming Soon" placeholder.

---

## Draft LinkedIn post (edit freely)

> I've been building **Smart Library App** — a multi-tenant Flask app that runs the whole back
> office of a reading-library / coaching-center business: enquiries, admissions, membership
> plans, fee collection, a full cashbook ledger, and a business-intelligence dashboard on top.
>
> A few things I'm happy with:
>
> • **One clean money flow.** Enquiry → admission → membership → payment → ledger → analytics,
>   written source-of-truth-first with real compensating rollback if a step fails.
>
> • **Migrated the database table by table.** I moved from SQLite to Supabase/Postgres one
>   table at a time — each slice dual-writing to a mirror with a documented removal condition —
>   instead of a risky big-bang cutover.
>
> • **Docs treated as code.** Per-file reference, architecture diagrams, an ADR log, and a
>   living technical-debt register. If the docs drift from the source, that's a bug.
>
> • **No buzzword inflation.** The built-in assistant is a rule-based "Smart Business
>   Assistant" that answers questions from the owner's real numbers — I deliberately didn't
>   slap "AI" on it for capability it doesn't have.
>
> Stack: Flask, Jinja2, Supabase (Postgres, no ORM), Bootstrap 5, Chart.js, deployed on a
> read-only serverless filesystem.
>
> #Flask #Python #Postgres #Supabase #WebDevelopment #BuildInPublic
