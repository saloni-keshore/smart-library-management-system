"""
Migration: Multi-tenant admin_id isolation.

Run once from the project root:
    python database/migrate.py

What it does:
  1. Adds admin_id to the enquiries table.
  2. Recreates the students table with admin_id + UNIQUE(mobile, admin_id)
     so two different libraries can have students with the same mobile number.
  3. Assigns ALL existing rows to the first admin in the database.
"""

from db import get_connection


def run():

    conn = get_connection()
    cursor = conn.cursor()

    # Disable FK enforcement so we can safely drop/recreate students
    cursor.execute("PRAGMA foreign_keys = OFF")

    # ── Find first admin ──────────────────────────────────────────────────────
    cursor.execute("SELECT admin_id FROM admins ORDER BY admin_id LIMIT 1")
    row = cursor.fetchone()

    if row is None:
        print("No admins found. Register an admin first, then run migration.")
        conn.close()
        return

    first_admin_id = row["admin_id"]
    print(f"Assigning all existing rows to admin_id = {first_admin_id}")

    # ── enquiries: simple ADD COLUMN ──────────────────────────────────────────
    cursor.execute("PRAGMA table_info(enquiries)")
    existing = [r["name"] for r in cursor.fetchall()]

    if "admin_id" not in existing:
        cursor.execute("ALTER TABLE enquiries ADD COLUMN admin_id INTEGER")
        cursor.execute(
            "UPDATE enquiries SET admin_id = ?", (first_admin_id,)
        )
        print("  enquiries.admin_id added and populated.")
    else:
        print("  enquiries.admin_id already exists — skipped.")

    # ── students: recreate with admin_id + composite UNIQUE ───────────────────
    cursor.execute("PRAGMA table_info(students)")
    existing = [r["name"] for r in cursor.fetchall()]

    if "admin_id" not in existing:
        cursor.execute("""
            CREATE TABLE students_new (
                student_id  INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id    INTEGER NOT NULL DEFAULT 1,
                enquiry_id  INTEGER,
                full_name   TEXT NOT NULL,
                mobile      TEXT NOT NULL,
                address     TEXT,
                id_proof    TEXT,
                purpose     TEXT,
                shift       TEXT,
                join_date   DATE,
                status      TEXT DEFAULT 'Active',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(mobile, admin_id)
            )
        """)

        cursor.execute(f"""
            INSERT INTO students_new
                (student_id, admin_id, enquiry_id, full_name, mobile,
                 address, id_proof, purpose, shift, join_date, status, created_at)
            SELECT
                student_id, {first_admin_id}, enquiry_id, full_name, mobile,
                address, id_proof, purpose, shift, join_date, status, created_at
            FROM students
        """)

        cursor.execute("DROP TABLE students")
        cursor.execute("ALTER TABLE students_new RENAME TO students")
        print("  students table recreated with admin_id and UNIQUE(mobile, admin_id).")
    else:
        print("  students.admin_id already exists — skipped.")

    cursor.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    run()
