-- Smart Library Pro Database Schema
-- Database: SQLite


PRAGMA foreign_keys = ON;


-- Admins

CREATE TABLE IF NOT EXISTS admins (
    admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
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
    full_name TEXT NOT NULL,
    mobile TEXT NOT NULL,
    purpose TEXT,
    preferred_shift TEXT,
    demo_done INTEGER DEFAULT 0,
    followup_date DATE,
    remarks TEXT,
    status TEXT DEFAULT 'Interested',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- Students

CREATE TABLE IF NOT EXISTS students (
    student_id INTEGER PRIMARY KEY AUTOINCREMENT,
    enquiry_id INTEGER,
    full_name TEXT NOT NULL,
    mobile TEXT,
    purpose TEXT,
    shift TEXT,
    join_date DATE,
    status TEXT DEFAULT 'Active',

    FOREIGN KEY (enquiry_id)
    REFERENCES enquiries(enquiry_id)
);


-- Memberships

CREATE TABLE IF NOT EXISTS memberships (
    membership_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    start_date DATE,
    end_date DATE,
    total_fee REAL,
    paid_amount REAL,
    pending_amount REAL DEFAULT 0,
    remarks TEXT,
    membership_status TEXT DEFAULT 'Active',

    FOREIGN KEY(student_id)
    REFERENCES students(student_id)
);


-- Payments

CREATE TABLE IF NOT EXISTS payments (
    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    membership_id INTEGER,
    receipt_number TEXT,
    payment_mode TEXT,
    amount REAL,
    payment_date DATE,
    remarks TEXT,

    FOREIGN KEY(membership_id)
    REFERENCES memberships(membership_id)
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