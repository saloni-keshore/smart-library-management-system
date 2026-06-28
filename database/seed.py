import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATABASE = BASE_DIR / "library.db"
SCHEMA = BASE_DIR / "schema.sql"


def initialize_database():

    connection = sqlite3.connect(DATABASE)

    with open(SCHEMA, "r", encoding="utf-8") as file:
        connection.executescript(file.read())

    cursor = connection.cursor()

    # Default Settings

    cursor.execute("""
        INSERT INTO settings
        (
            library_name,
            owner_name,
            receipt_mode,
            receipt_prefix,
            next_receipt_number
        )
        SELECT
            'Smart Library',
            '',
            'auto',
            'RCP-',
            1001
        WHERE NOT EXISTS
        (
            SELECT 1 FROM settings
        );
    """)

    connection.commit()
    connection.close()

    print("Database initialized successfully.")


if __name__ == "__main__":
    initialize_database()