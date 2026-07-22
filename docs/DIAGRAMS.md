# Diagrams

Five Mermaid diagrams (render natively on GitHub). Each is generated from the actual code — if a route, table, or import changes, update the matching diagram in the same change. These are single-source-of-truth here; other docs link to this file rather than re-embedding copies, so there's only one place to keep in sync.

## 1. Folder structure

```mermaid
graph TD
    Root["Smart Library App/"]
    Root --> AppPy["app.py"]
    Root --> ConfigPy["config.py (unused)"]
    Root --> Requirements["requirements.txt"]
    Root --> ReadmeRoot["README.md (empty)"]
    Root --> ClaudeMd["CLAUDE.md"]
    Root --> Database["database/"]
    Root --> Routes["routes/"]
    Root --> Templates["templates/"]
    Root --> Static["static/"]
    Root --> Utils["utils/"]
    Root --> Docs["docs/"]
    Root --> Empty["models/ services/ reports/ tests/ backups/ .agents/ (all empty)"]

    Database --> DBCore["db.py, schema.sql, seed.py"]
    Database --> DBMigrations["migrate_*.py (11 scripts, no version tracking)"]
    Database --> DBQueries["*_queries.py + cashbook_categories.py (10 modules)"]
    Database --> DBFile[("library.db")]

    Routes --> RouteFiles["13 blueprint modules, see FILE_REFERENCE.md"]

    Templates --> Layouts["layouts/ (base, auth_base, navbar, sidebar)"]
    Templates --> Components["components/ (~45 shared partials)"]
    Templates --> FeatureDirs["auth/ dashboard/ enquiries/ students/ memberships/ payments/ cashbook/ business_intelligence/ notification/ settings/ reports/"]

    Static --> CSS["css/ (6 files)"]
    Static --> JS["js/ (7 files)"]
    Static --> Charts["charts/ (3 server-generated PNGs)"]
    Static --> Uploads["uploads/settings/ (per-admin branding)"]
    Static --> Images["images/ (empty)"]
```

## 2. Application architecture (layered)

```mermaid
graph TD
    Browser["Browser"] --> Flask["app.py: create_app()"]

    Flask --> Auth["routes/auth.py"]
    Flask --> Dashboard["routes/dashboard.py"]
    Flask --> Enquiries["routes/enquiries.py"]
    Flask --> Student["routes/student.py"]
    Flask --> Membership["routes/membership.py"]
    Flask --> MembershipAnalytics["routes/membership_analytics.py"]
    Flask --> MembershipDistribution["routes/membership_distribution.py"]
    Flask --> Payment["routes/payment.py"]
    Flask --> Cashbook["routes/cashbook.py"]
    Flask --> BI["routes/business_intelligence.py"]
    Flask --> Notification["routes/notification.py"]
    Flask --> Setting["routes/setting.py"]
    Flask --> Report["routes/report.py"]
    Flask -. "context_processor: inject_notification_summary (every page render)" .-> Notification

    subgraph DataAccess ["Data Access Layer (database/)"]
        DB["db.py — get_connection()"]
        AuditQ["audit_queries.py"]
        BiQ["bi_queries.py"]
        CashQ["cashbook_queries.py"]
        MemSettQ["membership_settings_queries.py"]
        SettQ["settings_queries.py"]
        ReceiptSettQ["receipt_settings_queries.py"]
        NotifSettQ["notification_settings_queries.py"]
        BackupQ["backup_queries.py"]
        SecSettQ["security_settings_queries.py"]
        CatConst["cashbook_categories.py (constants only)"]
    end

    Charts["utils/charts.py (matplotlib)"]

    Auth --> DB
    Dashboard --> DB
    Dashboard --> Charts
    Dashboard --> CatConst
    Dashboard --> NotifSettQ
    Enquiries --> DB
    Student --> DB
    Membership --> DB
    Membership --> CashQ
    MembershipDistribution --> DB
    MembershipDistribution --> Charts
    Payment --> DB
    Payment --> CashQ
    Cashbook --> CashQ
    Cashbook --> AuditQ
    Cashbook --> CatConst
    BI --> CashQ
    BI --> BiQ
    Notification --> DB
    Setting --> SettQ
    Setting --> MemSettQ
    Setting --> ReceiptSettQ
    Setting --> NotifSettQ
    Setting --> BackupQ
    Setting --> SecSettQ
    app_ctx["app.py: inject_notification_summary()"] --> NotifSettQ

    CashQ --> AuditQ
    CashQ --> DB
    BiQ --> CashQ
    BiQ --> DB
    AuditQ --> DB
    ReceiptSettQ --> DB
    NotifSettQ --> DB
    BackupQ --> DB
    SecSettQ --> DB
    MemSettQ --> DB
    SettQ --> DB
    Charts --> DB

    DB --> SQLite[("library.db (SQLite)")]

    Auth -.->|render_template| Templates["Jinja templates → static PNGs / Chart.js JSON"]
    Dashboard -.->|render_template| Templates
    Cashbook -.->|render_template| Templates
    BI -.->|render_template| Templates
```

## 3. Request flow (Browser → Route → Database → Template)

```mermaid
sequenceDiagram
    participant B as Browser
    participant R as Flask route (routes/*.py)
    participant Q as Query module / raw SQL
    participant D as SQLite (library.db)
    participant T as Jinja template

    B->>R: HTTP request (e.g. GET /cashbook/)
    R->>R: if "admin_id" not in session: redirect("/")
    alt not logged in
        R-->>B: 302 redirect to "/"
    else logged in
        R->>Q: query function(admin_id, ...)
        Q->>D: SQL SELECT / INSERT / UPDATE
        D-->>Q: rows / rowcount
        Q-->>R: Python dict / list / sqlite3.Row
        opt write flow (membership/payment) — as of 2026-07-22, all three routes
        (membership.create, membership.renew, payment.collect) go through the
        same helper instead of each inlining this sequence
            R->>Q: record_payment(conn, admin_id, ...) [database/payment_queries.py]
            Q->>D: UPDATE library_settings SET next_receipt_number += 1
            Q->>D: INSERT INTO payments (receipt_number, ...)
            Q->>Q: insert_income_entry(conn, admin_id, ..., payment_id=payments.lastrowid)
            Q->>D: INSERT INTO cashbook (..., payment_id)
            Q->>Q: log_entry(cursor, ...) — same transaction
            D-->>Q: commit (all-or-nothing) / rollback on sqlite3.Error
        end
        R->>T: render_template(name, **context)
        T->>T: extends layouts/base.html, includes components/*
        T-->>R: rendered HTML
        R-->>B: 200 response
    end
```

## 4. Database relationships

```mermaid
erDiagram
    ADMINS ||--o{ ENQUIRIES : "admin_id"
    ADMINS ||--o{ STUDENTS : "admin_id"
    ADMINS ||--o{ AUDIT_LOG : "admin_id"
    ADMINS ||--|| LIBRARY_SETTINGS : "admin_id (unique)"
    ADMINS ||--|| MEMBERSHIP_SETTINGS : "admin_id (unique)"
    ADMINS ||--|| BACKUP_LOG : "admin_id (unique)"
    ADMINS ||--|| SECURITY_SETTINGS : "admin_id (unique)"
    ADMINS ||--o{ CASHBOOK : "admin_id (no FK — added via ALTER)"
    ADMINS ||--o{ EXPENSES : "admin_id (no FK, unused table)"
    ENQUIRIES |o--o| STUDENTS : "enquiry_id (nullable)"
    STUDENTS ||--o{ MEMBERSHIPS : "student_id"
    STUDENTS ||--o{ PAYMENTS : "student_id"
    MEMBERSHIPS ||--o{ PAYMENTS : "membership_id"
    PAYMENTS |o--o| CASHBOOK : "payment_id (auto-generated entries only — actually populated as of 2026-07-22, previously declared but always NULL, see TD-22 resolution)"
    CASHBOOK ||--o{ AUDIT_LOG : "entry_id"

    ADMINS {
        int admin_id PK
        text username UK
        text mobile UK
        text password
        text role
    }
    ENQUIRIES {
        int enquiry_id PK
        int admin_id FK
        text status
    }
    STUDENTS {
        int student_id PK
        int admin_id FK
        int enquiry_id FK
        text mobile
        text status
    }
    MEMBERSHIPS {
        int membership_id PK
        int student_id FK
        text plan_name
        date end_date
        real total_fee
        real paid_amount
        real pending_amount
        text membership_status
    }
    PAYMENTS {
        int payment_id PK
        int membership_id FK
        int student_id FK
        text receipt_number UK
        real amount_paid
    }
    CASHBOOK {
        int entry_id PK
        text type
        text category
        real amount
        int admin_id "no FK"
        text source
        text reference_id
    }
    AUDIT_LOG {
        int log_id PK
        int admin_id FK
        int entry_id FK
        text action
    }
    LIBRARY_SETTINGS {
        int setting_id PK
        int admin_id FK "unique"
        int reminder_7_days "Notification Settings"
        int notify_in_app "Notification Settings"
        int quiet_hours_enabled "Notification Settings"
        int dash_show_pending_fees "Notification Settings"
    }
    MEMBERSHIP_SETTINGS {
        int setting_id PK
        int admin_id FK "unique"
        int reminder_days "unused, superseded (TD-23)"
        int send_reminders "unused, superseded (TD-23)"
    }
    BACKUP_LOG {
        int log_id PK
        int admin_id FK "unique"
        timestamp last_backup_at
        text backup_filename
    }
    SECURITY_SETTINGS {
        int setting_id PK
        int admin_id FK "unique"
        int session_timeout_minutes
        int remember_me_enabled
        int login_notifications_enabled
    }
    EXPENSES {
        int expense_id PK
        int admin_id "no FK, unused"
    }
```

`settings` (legacy) and `transactions` (defined twice, see [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md)) are omitted here since neither is used by any route today — see [11_FUTURE_WORK.md](11_FUTURE_WORK.md) TD-2/TD-4.

## 5. Module dependency graph (literal Python imports, verified by grep on 2026-07-20, updated 2026-07-21 for `database/membership_queries.py`, updated 2026-07-22 for `database/payment_queries.py`)

```mermaid
graph LR
    app_py["app.py"]

    subgraph Routes["routes/"]
        auth_py["auth.py"]
        dashboard_py["dashboard.py"]
        enquiries_py["enquiries.py"]
        student_py["student.py"]
        membership_py["membership.py"]
        membership_analytics_py["membership_analytics.py"]
        membership_distribution_py["membership_distribution.py"]
        payment_py["payment.py"]
        cashbook_py["cashbook.py"]
        business_intelligence_py["business_intelligence.py"]
        notification_py["notification.py"]
        setting_py["setting.py"]
        report_py["report.py"]
    end

    subgraph DB["database/"]
        db_py["db.py"]
        audit_queries_py["audit_queries.py"]
        bi_queries_py["bi_queries.py"]
        cashbook_queries_py["cashbook_queries.py"]
        cashbook_categories_py["cashbook_categories.py"]
        payment_queries_py["payment_queries.py"]
        membership_settings_queries_py["membership_settings_queries.py"]
        membership_queries_py["membership_queries.py"]
        settings_queries_py["settings_queries.py"]
        receipt_settings_queries_py["receipt_settings_queries.py"]
        notification_settings_queries_py["notification_settings_queries.py"]
        backup_queries_py["backup_queries.py"]
        security_settings_queries_py["security_settings_queries.py"]
    end

    charts_py["utils/charts.py"]

    app_py --> auth_py
    app_py --> dashboard_py
    app_py --> enquiries_py
    app_py --> student_py
    app_py --> membership_py
    app_py --> membership_analytics_py
    app_py --> membership_distribution_py
    app_py --> payment_py
    app_py --> cashbook_py
    app_py --> business_intelligence_py
    app_py --> notification_py
    app_py --> setting_py
    app_py --> report_py

    auth_py --> db_py
    dashboard_py --> db_py
    dashboard_py --> charts_py
    dashboard_py --> cashbook_categories_py
    dashboard_py --> cashbook_queries_py
    dashboard_py --> membership_queries_py
    enquiries_py --> db_py
    student_py --> db_py
    student_py --> membership_queries_py
    membership_py --> db_py
    membership_py --> payment_queries_py
    membership_py --> membership_settings_queries_py
    membership_py --> membership_queries_py
    membership_distribution_py --> db_py
    membership_distribution_py --> charts_py
    membership_distribution_py --> cashbook_queries_py
    membership_distribution_py --> membership_queries_py
    payment_py --> db_py
    payment_py --> payment_queries_py
    payment_queries_py --> cashbook_queries_py
    cashbook_py --> cashbook_queries_py
    cashbook_py --> audit_queries_py
    cashbook_py --> cashbook_categories_py
    business_intelligence_py --> cashbook_queries_py
    business_intelligence_py --> bi_queries_py
    notification_py --> db_py
    notification_py --> membership_queries_py
    setting_py --> settings_queries_py
    setting_py --> membership_settings_queries_py
    setting_py --> receipt_settings_queries_py
    setting_py --> notification_settings_queries_py
    setting_py --> backup_queries_py
    setting_py --> security_settings_queries_py
    app_py -.->|"inject_notification_summary()"| notification_settings_queries_py
    dashboard_py --> notification_settings_queries_py

    cashbook_queries_py --> db_py
    cashbook_queries_py --> audit_queries_py
    bi_queries_py --> db_py
    bi_queries_py --> cashbook_queries_py
    audit_queries_py --> db_py
    membership_settings_queries_py --> db_py
    membership_queries_py --> db_py
    settings_queries_py --> db_py
    receipt_settings_queries_py --> db_py
    notification_settings_queries_py --> db_py
    backup_queries_py --> db_py
    security_settings_queries_py --> db_py
    charts_py --> db_py
```

`membership_analytics.py` and `report.py` have no data-layer imports (both are stubs — see [11_FUTURE_WORK.md](11_FUTURE_WORK.md)). Migration scripts (`database/migrate_*.py`) are omitted — they're standalone-run, not part of the request-time import graph; see their individual cards in [FILE_REFERENCE.md](FILE_REFERENCE.md) for their (inconsistent) import style.
