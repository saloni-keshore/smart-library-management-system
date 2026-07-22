import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "library.db"))

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_enquiries_admin_created ON enquiries(admin_id, enquiry_id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_students_admin_status ON students(admin_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_students_enquiry_admin ON students(enquiry_id, admin_id)",
    "CREATE INDEX IF NOT EXISTS idx_memberships_student_end ON memberships(student_id, end_date)",
    "CREATE INDEX IF NOT EXISTS idx_payments_student_date ON payments(student_id, payment_date)",
    "CREATE INDEX IF NOT EXISTS idx_cashbook_admin_date_type ON cashbook(admin_id, entry_date, type)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_admin_created ON audit_log(admin_id, created_at DESC)",
)


def get_connection():
    """Return a short-lived, production-configured SQLite connection."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def initialize_database():
    """Set safe SQLite defaults and create indexes required by common queries."""
    with get_connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        for statement in INDEXES:
            connection.execute(statement)
