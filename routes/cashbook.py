import calendar

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from database.cashbook_queries import (
    insert_transaction,
    get_total_income,
    get_total_expense,
    get_pending_fees,
    get_monthly_income,
    get_monthly_expense,
    get_income_category_totals,
    get_expense_category_totals,
    get_payment_method_distribution,
    get_cash_balance,
    get_todays_transaction_count,
    get_cashbook_ledger,
    get_transaction_by_id,
    update_manual_transaction
)

cashbook_bp = Blueprint(
    "cashbook",
    __name__,
    url_prefix="/cashbook"
)

# Existing application color palette (see utils/charts.py and
# static/css/membership_distribution.css) - reused here, not invented.
CHART_PALETTE = [
    "#2563eb",  # primary blue
    "#16a34a",  # success green
    "#f59e0b",  # warning amber
    "#7c3aed",  # purple
    "#ef4444",  # danger red
    "#06b6d4",  # cyan
]
CHART_FALLBACK_COLOR = "#94a3b8"

PAYMENT_METHOD_COLORS = {
    "Cash": "#16a34a",
    "UPI": "#2563eb",
    "Bank Transfer": "#7c3aed",
}

# Filter dropdown options - static enums, not sourced from the DB (same as
# the payment method / transaction type choices already in the Add
# Transaction modal).
FILTER_TRANSACTION_TYPES = ["Income", "Expense"]
FILTER_CATEGORIES = [
    "Admission Fee", "Membership Fee", "Membership Renewal", "Misc Income",
    "Electricity", "Internet", "Furniture", "Books", "Salary", "Repairs",
    "Misc Expenses",
]
FILTER_PAYMENT_METHODS = ["Cash", "UPI", "Bank Transfer"]
FILTER_SOURCES = ["Admission", "Renewal", "Payments", "Cashbook Manual Entry"]

TRANSACTIONS_PER_PAGE = 10


def _month_label(month_key):
    year, month = month_key.split("-")
    return f"{calendar.month_abbr[int(month)]} {year}"


def _build_income_expense_chart(admin_id):
    """Chart.js-ready {labels, datasets} for the Income vs Expense trend.

    Profit is derived locally from the income/expense totals already
    fetched here instead of calling get_monthly_profit(), which would
    re-run the same two SQL queries again.
    """

    income = get_monthly_income(admin_id)
    expense = get_monthly_expense(admin_id)

    months = sorted(set(income) | set(expense))
    profit = {m: income.get(m, 0) - expense.get(m, 0) for m in months}

    return {
        "labels": [_month_label(m) for m in months],
        "datasets": [
            {
                "label": "Income",
                "data": [income.get(m, 0) for m in months],
                "borderColor": "#16a34a",
                "backgroundColor": "rgba(22, 163, 74, 0.12)",
                "tension": 0.4,
                "fill": True
            },
            {
                "label": "Expense",
                "data": [expense.get(m, 0) for m in months],
                "borderColor": "#ef4444",
                "backgroundColor": "rgba(239, 68, 68, 0.12)",
                "tension": 0.4,
                "fill": True
            },
            {
                "label": "Profit",
                "data": [profit[m] for m in months],
                "borderColor": "#2563eb",
                "backgroundColor": "rgba(37, 99, 235, 0.12)",
                "tension": 0.4,
                "fill": True
            }
        ]
    }


def _build_category_chart(totals):
    """Chart.js-ready {labels, datasets} for a category totals dict."""

    labels = list(totals.keys())
    data = list(totals.values())
    colors = [
        CHART_PALETTE[i % len(CHART_PALETTE)]
        for i in range(len(labels))
    ]

    return {
        "labels": labels,
        "datasets": [{
            "data": data,
            "backgroundColor": colors
        }]
    }


def _build_payment_method_chart(admin_id):
    """Chart.js-ready {labels, datasets} for payment method distribution."""

    totals = get_payment_method_distribution(admin_id)
    labels = list(totals.keys())
    data = list(totals.values())
    colors = [
        PAYMENT_METHOD_COLORS.get(label, CHART_FALLBACK_COLOR)
        for label in labels
    ]

    return {
        "labels": labels,
        "datasets": [{
            "data": data,
            "backgroundColor": colors
        }]
    }


@cashbook_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    filters = {
        "search": request.args.get("search", "").strip(),
        "date_from": request.args.get("date_from", "").strip(),
        "date_to": request.args.get("date_to", "").strip(),
        "transaction_type": request.args.get("transaction_type", "").strip(),
        "category": request.args.get("category", "").strip(),
        "payment_method": request.args.get("payment_method", "").strip(),
        "source": request.args.get("source", "").strip(),
        "status": request.args.get("status", "").strip(),
    }

    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1

    ledger = get_cashbook_ledger(
        admin_id,
        search=filters["search"] or None,
        date_from=filters["date_from"] or None,
        date_to=filters["date_to"] or None,
        transaction_type=filters["transaction_type"] or None,
        category=filters["category"] or None,
        payment_method=filters["payment_method"] or None,
        source=filters["source"] or None,
        page=page,
        per_page=TRANSACTIONS_PER_PAGE
    )

    total_income = get_total_income(admin_id)
    total_expense = get_total_expense(admin_id)
    net_profit = total_income - total_expense
    pending_fees = get_pending_fees(admin_id)
    cash_balance = get_cash_balance(admin_id)
    todays_transactions = get_todays_transaction_count(admin_id)

    income_expense_chart = _build_income_expense_chart(admin_id)
    expense_category_chart = _build_category_chart(get_expense_category_totals(admin_id))
    revenue_source_chart = _build_category_chart(get_income_category_totals(admin_id))
    payment_method_chart = _build_payment_method_chart(admin_id)

    return render_template(
        "cashbook/index.html",
        ledger=ledger,
        filters=filters,
        filter_transaction_types=FILTER_TRANSACTION_TYPES,
        filter_categories=FILTER_CATEGORIES,
        filter_payment_methods=FILTER_PAYMENT_METHODS,
        filter_sources=FILTER_SOURCES,
        total_income=total_income,
        total_expense=total_expense,
        net_profit=net_profit,
        pending_fees=pending_fees,
        cash_balance=cash_balance,
        todays_transactions=todays_transactions,
        income_expense_chart=income_expense_chart,
        expense_category_chart=expense_category_chart,
        revenue_source_chart=revenue_source_chart,
        payment_method_chart=payment_method_chart
    )


@cashbook_bp.route("/add", methods=["POST"])
def add_transaction():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    transaction_type = request.form.get("transaction_type")
    category = request.form.get("category")
    amount = request.form.get("amount")
    payment_method = request.form.get("payment_method")
    entry_date = request.form.get("transaction_date")
    person = request.form.get("person")
    description = request.form.get("description")

    insert_transaction(
        admin_id,
        transaction_type,
        category,
        person,
        description,
        amount,
        payment_method,
        entry_date
    )

    return redirect(url_for("cashbook.index"))


@cashbook_bp.route("/edit/<int:entry_id>", methods=["POST"])
def edit_transaction(entry_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    entry = get_transaction_by_id(admin_id, entry_id)

    if entry is None:
        flash("Transaction not found.", "danger")
        return redirect(url_for("cashbook.index"))

    if entry["source"] != "Cashbook Manual Entry":
        flash("Automatic ledger entries cannot be edited.", "warning")
        return redirect(url_for("cashbook.index"))

    category = request.form.get("category")
    amount = request.form.get("amount")
    payment_method = request.form.get("payment_method")
    entry_date = request.form.get("transaction_date")
    person = request.form.get("person")
    description = request.form.get("description")

    update_manual_transaction(
        admin_id,
        entry_id,
        category,
        person,
        description,
        amount,
        payment_method,
        entry_date
    )

    flash("Transaction updated successfully.", "success")
    return redirect(url_for("cashbook.index"))
