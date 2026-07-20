from database.db import get_connection


def get_membership_settings(admin_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM membership_settings
        WHERE admin_id = ?
        """,
        (admin_id,)
    )

    row = cursor.fetchone()

    conn.close()

    return row


def save_membership_settings(admin_id, data):
    """Insert/update this admin's plan pricing and renewal policy.

    reminder_days/send_reminders are intentionally omitted here - reminder
    ownership moved to Settings > Notification Settings
    (library_settings.reminder_*/notify_* columns). Omitting them from the
    INSERT/UPDATE leaves any existing values on this table untouched instead
    of overwriting them with stale form data. See docs/11_FUTURE_WORK.md.
    """

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO membership_settings(

            admin_id,

            monthly_fee,
            monthly_days,

            quarterly_fee,
            quarterly_days,

            half_yearly_fee,
            half_yearly_days,

            yearly_fee,
            yearly_days,

            admission_fee,

            late_fee_per_day,

            renewal_grace_days,

            auto_expiry,

            allow_early_renewal

        )

        VALUES(

            ?,?,?,?,?,?,?,?,?,?,?,?,?

        )

        ON CONFLICT(admin_id)

        DO UPDATE SET

        monthly_fee=excluded.monthly_fee,
        monthly_days=excluded.monthly_days,

        quarterly_fee=excluded.quarterly_fee,
        quarterly_days=excluded.quarterly_days,

        half_yearly_fee=excluded.half_yearly_fee,
        half_yearly_days=excluded.half_yearly_days,

        yearly_fee=excluded.yearly_fee,
        yearly_days=excluded.yearly_days,

        admission_fee=excluded.admission_fee,

        late_fee_per_day=excluded.late_fee_per_day,

        renewal_grace_days=excluded.renewal_grace_days,

        auto_expiry=excluded.auto_expiry,

        allow_early_renewal=excluded.allow_early_renewal,
        updated_at=CURRENT_TIMESTAMP
        """,

        (

            admin_id,

            data["monthly_fee"],
            data["monthly_days"],

            data["quarterly_fee"],
            data["quarterly_days"],

            data["half_yearly_fee"],
            data["half_yearly_days"],

            data["yearly_fee"],
            data["yearly_days"],

            data["admission_fee"],

            data["late_fee_per_day"],

            data["renewal_grace_days"],

            data["auto_expiry"],

            data["allow_early_renewal"]

        )

    )

    conn.commit()

    conn.close()
