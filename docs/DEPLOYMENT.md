# Production deployment

**As of 2026-07-25 (ADR-32, Phase 11), the app has no local database of its own** — Supabase (PostgreSQL) is the only datastore, reached over the network via `database/supabase_client.py`. The SQLite-specific steps this doc used to describe (`DATABASE_PATH`, `database.init_db`, local file backups) no longer apply; see [DECISIONS.md](DECISIONS.md) for the full migration history.

1. Create a Python virtual environment and install `requirements.txt`.
2. Set the variables shown in `.env.example` in the process environment, including `SUPABASE_URL`/`SUPABASE_SECRET_KEY` (see `database/supabase_client.py`). Do not commit `.env`.
3. Confirm the target Supabase project's schema matches `database/supabase_migration.sql` (applied by hand in the Supabase SQL Editor — there is no migrations framework/runner).
4. Serve with a production WSGI server, for example `waitress-serve --call wsgi:create_app`, behind HTTPS.
5. Backups are Supabase's responsibility at the infrastructure level (point-in-time recovery / scheduled dumps, configured in the Supabase project itself) — the app's own Settings → Data & Backup → "Create Backup" is a manual, per-admin data export (JSON), not a substitute for a real database backup strategy.

Because there's no local file to share or lock, multiple independent web workers or hosts can safely point at the same Supabase project concurrently — the constraint SQLite had (no shared file over a network filesystem) no longer applies.
