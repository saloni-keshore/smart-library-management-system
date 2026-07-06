from database.db import get_connection

conn = get_connection()

cursor = conn.cursor()

cursor.execute("""

CREATE TABLE IF NOT EXISTS membership_settings (

    plan_id INTEGER PRIMARY KEY AUTOINCREMENT,

    admin_id INTEGER NOT NULL,

    plan_name TEXT NOT NULL,

    duration_months INTEGER NOT NULL,

    admission_fee REAL DEFAULT 0,

    membership_fee REAL NOT NULL,

    security_deposit REAL DEFAULT 0,

    grace_days INTEGER DEFAULT 0,

    is_active INTEGER DEFAULT 1,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

)

""")

conn.commit()

conn.close()

print("membership_settings table created.")