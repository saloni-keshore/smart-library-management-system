"""Create a fresh Smart Library SQLite database from the canonical schema.

Run once for a new deployment, after setting DATABASE_PATH if the database
should live outside the application directory:

    python -m database.init_db
"""

from database.db import DATABASE_PATH, get_connection


def run():
    if DATABASE_PATH.exists() and DATABASE_PATH.stat().st_size > 0:
        raise RuntimeError(
            f"Refusing to initialize existing database: {DATABASE_PATH}. "
            "Use the migration tools for an existing installation."
        )

    schema_path = DATABASE_PATH.parent / "schema.sql"
    with get_connection() as connection:
        connection.executescript(schema_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    run()
