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
    mobile TEXT NOT NULL UNIQUE,
    address TEXT,
    id_proof TEXT,
    purpose TEXT,
    shift TEXT,
    join_date DATE,
    status TEXT DEFAULT 'Active',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (enquiry_id)
    REFERENCES enquiries(enquiry_id)
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