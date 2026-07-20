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
    receipt_prefix TEXT DEFAULT 'LIB',
    next_receipt_number INTEGER DEFAULT 1001,
    auto_increment_receipt INTEGER DEFAULT 1,
    print_logo INTEGER DEFAULT 1,
    print_stamp INTEGER DEFAULT 1,
    print_signature INTEGER DEFAULT 1,
    paper_size TEXT DEFAULT 'A4',
    auto_print INTEGER DEFAULT 0,
    auto_email INTEGER DEFAULT 0,
    open_pdf_after_save INTEGER DEFAULT 1,
    duplicate_copy INTEGER DEFAULT 0,

    -- Notification Settings (Reminder Rules)
    reminder_7_days INTEGER DEFAULT 1,
    reminder_3_days INTEGER DEFAULT 1,
    reminder_1_day INTEGER DEFAULT 1,
    notify_on_expiry_day INTEGER DEFAULT 1,
    notify_after_expiry INTEGER DEFAULT 1,

    -- Notification Settings (Channels)
    notify_in_app INTEGER DEFAULT 1,
    notify_sms INTEGER DEFAULT 0,
    notify_email INTEGER DEFAULT 0,
    notify_whatsapp INTEGER DEFAULT 0,

    -- Notification Settings (Quiet Hours)
    quiet_hours_enabled INTEGER DEFAULT 0,
    quiet_hours_start TEXT DEFAULT '22:00',
    quiet_hours_end TEXT DEFAULT '07:00',
    quiet_hours_allow_critical INTEGER DEFAULT 1,

    -- Notification Settings (Dashboard Notifications)
    dash_show_badge_count INTEGER DEFAULT 1,
    dash_show_expiry_today INTEGER DEFAULT 1,
    dash_show_expiry_tomorrow INTEGER DEFAULT 1,
    dash_show_overdue INTEGER DEFAULT 1,
    dash_show_pending_fees INTEGER DEFAULT 1,
    dash_show_new_admissions INTEGER DEFAULT 1,

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
-- NOTE: reminder_days/send_reminders are superseded by the notification_*/
-- reminder_* columns on library_settings (Settings > Notification Settings
-- now owns reminder behaviour) - kept here unused for backward compatibility,
-- see docs/11_FUTURE_WORK.md.

CREATE TABLE IF NOT EXISTS membership_settings (
    setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL UNIQUE,
    monthly_fee REAL NOT NULL DEFAULT 0,
    monthly_days INTEGER NOT NULL DEFAULT 30,
    quarterly_fee REAL NOT NULL DEFAULT 0,
    quarterly_days INTEGER NOT NULL DEFAULT 90,
    half_yearly_fee REAL NOT NULL DEFAULT 0,
    half_yearly_days INTEGER NOT NULL DEFAULT 180,
    yearly_fee REAL NOT NULL DEFAULT 0,
    yearly_days INTEGER NOT NULL DEFAULT 365,
    admission_fee REAL NOT NULL DEFAULT 0,
    late_fee_per_day REAL NOT NULL DEFAULT 0,
    renewal_grace_days INTEGER NOT NULL DEFAULT 7,
    auto_expiry INTEGER NOT NULL DEFAULT 1 CHECK (auto_expiry IN (0, 1)),
    allow_early_renewal INTEGER NOT NULL DEFAULT 1 CHECK (allow_early_renewal IN (0, 1)),
    send_reminders INTEGER NOT NULL DEFAULT 1 CHECK (send_reminders IN (0, 1)),
    reminder_days INTEGER NOT NULL DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
);

-- Data & Backup: one row per admin, tracks the last manual backup taken.
-- Kept separate from library_settings because a backup can be taken before
-- a Library Profile row exists (library_settings.library_name/phone are
-- NOT NULL, so it can't hold a lazily-created bare row).
CREATE TABLE IF NOT EXISTS backup_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL UNIQUE,
    last_backup_at TIMESTAMP,
    backup_filename TEXT,
    FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
);

-- Security Settings: one row per admin. Kept separate from library_settings
-- for the same reason as backup_log.
CREATE TABLE IF NOT EXISTS security_settings (
    setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL UNIQUE,
    session_timeout_minutes INTEGER NOT NULL DEFAULT 60,
    remember_me_enabled INTEGER NOT NULL DEFAULT 0 CHECK (remember_me_enabled IN (0, 1)),
    login_notifications_enabled INTEGER NOT NULL DEFAULT 0 CHECK (login_notifications_enabled IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
);
