# Production deployment

1. Create a Python virtual environment and install `requirements.txt`.
2. Set the variables shown in `.env.example` in the process environment. Do not commit `.env`.
3. Set `DATABASE_PATH` to a writable persistent volume outside the deployed source tree.
4. For a new database only, run `python -m database.init_db` once.
5. Serve with a production WSGI server, for example `waitress-serve --call wsgi:create_app`, behind HTTPS.
6. Back up the SQLite database to protected storage and periodically restore-test a backup.

SQLite is appropriate for a single application host. Multiple independent web
workers or hosts must not share the same SQLite file over a network filesystem.
