from db import get_connection


def run():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (

            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,

            admin_id INTEGER NOT NULL,

            transaction_type TEXT NOT NULL,

            category TEXT NOT NULL,

            person TEXT,

            amount REAL NOT NULL,

            payment_method TEXT,

            transaction_date DATE,

            description TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(admin_id)
                REFERENCES admins(admin_id)

        )
    """)

    conn.commit()
    conn.close()

    print("Transactions table created successfully.")


if __name__ == "__main__":
    run()