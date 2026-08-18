from flask import Blueprint, jsonify, request, session

from database.search_queries import global_search

search_bp = Blueprint("search", __name__, url_prefix="/search")


@search_bp.route("/suggestions")
def suggestions():
    """JSON autocomplete source for the navbar's global search (ADR-44) -
    the same explicit-selection-only contract as
    routes.ai_center.student_suggestions() (ADR-41): typing alone never
    navigates anywhere, only an explicit click/Enter selection does."""

    if "admin_id" not in session:
        return jsonify({}), 401

    results = global_search(session["admin_id"], request.args.get("q", ""))

    return jsonify({
        "students": [
            {
                "student_id": s["student_id"],
                "full_name": s["full_name"],
                "mobile": s.get("mobile"),
            }
            for s in results["students"]
        ],
        "payments": [
            {
                "payment_id": p["payment_id"],
                "receipt_number": p["receipt_number"],
                "full_name": p.get("full_name"),
                "amount_paid": p.get("amount_paid"),
            }
            for p in results["payments"]
        ],
        "enquiries": [
            {
                "enquiry_id": e["enquiry_id"],
                "full_name": e["full_name"],
                "mobile": e.get("mobile"),
                "purpose": e.get("purpose"),
            }
            for e in results["enquiries"]
        ],
        "cashbook": [
            {
                "entry_id": c["entry_id"],
                "category": c.get("category"),
                "person": c.get("person"),
                "amount": c.get("amount"),
                "type": c.get("type"),
            }
            for c in results["cashbook"]
        ],
    })
