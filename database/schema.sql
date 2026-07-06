-- Smart Library Pro Database Schema
-- Database: SQLite


PRAGMA foreign_keys = ON;


-- Admins

CREATE TABLE IF NOT EXISTS admins (
    admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    mobile TEXT NOT NULL UNIQUE,
    email TEXT,
    role TEXT DEFAULT 'admin',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- Settings

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_name TEXT NOT NULL,
    owner_name TEXT,
    mobile TEXT,
    address TEXT,
    logo TEXT,
    receipt_mode TEXT DEFAULT 'auto',
    receipt_prefix TEXT DEFAULT 'RCP-',
    next_receipt_number INTEGER DEFAULT 1001
);


-- Enquiries

CREATE TABLE IF NOT EXISTS enquiries (
    enquiry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    full_name TEXT NOT NULL,
    mobile TEXT NOT NULL,
    purpose TEXT,
    preferred_shift TEXT,
    demo_done INTEGER DEFAULT 0,
    followup_date DATE,
    remarks TEXT,
    status TEXT DEFAULT 'Interested',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
);


-- Students

CREATE TABLE IF NOT EXISTS students (
    student_id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    enquiry_id INTEGER,
    full_name TEXT NOT NULL,
    mobile TEXT NOT NULL,
    address TEXT,
    id_proof TEXT,
    purpose TEXT,
    shift TEXT,
    join_date DATE,
    status TEXT DEFAULT 'Active',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(mobile, admin_id),

    FOREIGN KEY (admin_id) REFERENCES admins(admin_id),
    FOREIGN KEY (enquiry_id) REFERENCES enquiries(enquiry_id)
);


-- Memberships

CREATE TABLE IF NOT EXISTS memberships (
    membership_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    plan_name TEXT NOT NULL,
    joining_date DATE NOT NULL,
    duration_days INTEGER ,
    end_date DATE NOT NULL,
    total_fee REAL NOT NULL,
    paid_amount REAL DEFAULT 0,
    pending_amount REAL DEFAULT 0,
    remarks TEXT,
    membership_status TEXT DEFAULT 'Active',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(student_id)
    REFERENCES students(student_id)
);


-- Payments

CREATE TABLE IF NOT EXISTS payments (

    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,

    membership_id INTEGER NOT NULL,

    student_id INTEGER NOT NULL,

    receipt_number TEXT UNIQUE,

    payment_mode TEXT NOT NULL,

    amount_paid REAL NOT NULL,

    payment_date DATE DEFAULT CURRENT_DATE,

    remarks TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (membership_id)
    REFERENCES memberships(membership_id),

    FOREIGN KEY (student_id)
    REFERENCES students(student_id)

);


-- Cashbook

CREATE TABLE IF NOT EXISTS cashbook (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    description TEXT,
    amount REAL,
    entry_date DATE,
    payment_id INTEGER,

    FOREIGN KEY(payment_id)
    REFERENCES payments(payment_id)
);

-- expense table 
CREATE TABLE expenses (

    expense_id INTEGER PRIMARY KEY AUTOINCREMENT,

    admin_id INTEGER NOT NULL,

    title TEXT NOT NULL,

    category TEXT NOT NULL,

    amount REAL NOT NULL,

    payment_method TEXT,

    vendor TEXT,

    notes TEXT,

    expense_date DATE NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

);

--transaction table
CREATE TABLE IF NOT EXISTS transactions (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    transaction_type TEXT NOT NULL,

    category TEXT NOT NULL,

    person TEXT,

    amount REAL NOT NULL,

    payment_method TEXT,

    transaction_date TEXT,

    description TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

);

-- Audit Trail: one row per financial change (auto or manual) to cashbook
CREATE TABLE IF NOT EXISTS audit_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    entry_id INTEGER,
    action TEXT NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES admins(admin_id),
    FOREIGN KEY (entry_id) REFERENCES cashbook(entry_id)
);

-- Library Settings: one row per admin, holds the Settings > Library Profile form
CREATE TABLE IF NOT EXISTS library_settings (
    setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL UNIQUE,
    library_name TEXT NOT NULL,
    owner_name TEXT,
    phone TEXT NOT NULL,
    email TEXT,
    address TEXT,
    city TEXT,
    state TEXT,
    pincode TEXT,
    opening_time TEXT,
    closing_time TEXT,
    weekly_holiday TEXT,
    logo_path TEXT,
    stamp_path TEXT,
    signature_path TEXT,
    receipt_footer TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
);

--adding columns to cashbook table
ALTER TABLE cashbook
ADD COLUMN category TEXT;

ALTER TABLE cashbook
ADD COLUMN person TEXT;

ALTER TABLE cashbook
ADD COLUMN admin_id INTEGER;

ALTER TABLE cashbook
ADD COLUMN payment_method TEXT;

-- Financial ledger: unique reference number + origin of every entry
ALTER TABLE cashbook
ADD COLUMN reference_id TEXT;

ALTER TABLE cashbook
ADD COLUMN source TEXT;

--membership_settings Table

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

);