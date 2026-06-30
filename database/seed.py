import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash

BASE_DIR = Path(__file__).resolve().parent

DATABASE = BASE_DIR / "library.db"
SCHEMA = BASE_DIR / "schema.sql"


def initialize_database():

    connection = sqlite3.connect(DATABASE)

    with open(SCHEMA, "r", encoding="utf-8") as file:
        connection.executescript(file.read())

    cursor = connection.cursor()




    connection.commit()
    connection.close()

    print("Database initialized successfully.")


if __name__ == "__main__":
    initialize_database()