"""
Single source of truth for Cashbook category lists.

Routes (cashbook, dashboard) and templates all import from here instead of
keeping their own copies, so the categories shown in a <select> can never
drift from the categories the server accepts.

Automatic categories are never offered in a manual-entry form - they only
ever get created by insert_income_entry() (Admission/Renewal/Payments
routes), which is what guarantees a student fee payment can never be
double-booked as a manual Cashbook entry.
"""

AUTO_CATEGORIES = [
    "Admission Fee",
    "Membership Fee",
    "Membership Renewal",
    # Membership extra charges (ADR-66) - created only by record_payment()'s
    # per-component split when a membership is sold/renewed with the matching
    # charge applied. Never manually enterable, same as the three above.
    "Seat Reservation",
    "Locker",
    "Security Deposit",
    # Walk-in / Day Pass (ADR-71) - created only by record_payment() when a
    # "Day Pass" plan membership is sold/renewed for a Casual student. Never
    # manually enterable: the student's membership/payment history is the
    # record, so it can't be double-booked from the Cashbook form.
    "Day Pass",
]

MANUAL_INCOME_CATEGORIES = [
    "Donation",
    "Library Fine",
    "Book Sale",
    "Membership Card Fee",
    "Other Income",
]

MANUAL_EXPENSE_CATEGORIES = [
    "Electricity Bill",
    "Internet Bill",
    "Rent",
    "Salary",
    "Maintenance",
    "Cleaning",
    "Furniture",
    "Stationery",
    "Tea & Snacks",
    "Other Expenses",
    # Returned to a member when their refundable Security Deposit (ADR-66) is
    # given back - written by routes/membership.py's refund_charge() via
    # insert_transaction(), and manually enterable too.
    "Security Deposit Refund",
]

ALL_CATEGORIES = AUTO_CATEGORIES + MANUAL_INCOME_CATEGORIES + MANUAL_EXPENSE_CATEGORIES

PAYMENT_METHODS = ["Cash", "UPI", "Card", "Bank Transfer"]
