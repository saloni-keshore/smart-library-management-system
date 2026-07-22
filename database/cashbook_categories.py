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
]

ALL_CATEGORIES = AUTO_CATEGORIES + MANUAL_INCOME_CATEGORIES + MANUAL_EXPENSE_CATEGORIES

PAYMENT_METHODS = ["Cash", "UPI", "Card", "Bank Transfer"]
