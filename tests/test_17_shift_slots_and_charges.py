"""Pure-unit tests for the ADR-65/66/67 pricing + bucketing helpers.

These touch no database, so they run even when the Supabase-backed suite
can't connect.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.membership_queries import (  # noqa: E402
    derive_time_bucket,
    resolve_slot_bucket,
    compute_slot_charge,
    split_payment_across_buckets,
    split_admission_and_membership_fee,
    describe_time_buckets,
    PLAN_MONTHS,
)
from database.shift_slots_queries import _slot_span_hours  # noqa: E402
from database.membership_charges_queries import get_charge_config, CHARGE_CATALOG  # noqa: E402
from database.bi_queries import _membership_bucket, CANONICAL_SHIFTS, FULL_DAY_LABEL  # noqa: E402


# --- derive_time_bucket -----------------------------------------------------

def test_bucket_boundaries():
    assert derive_time_bucket("05:00") == "Morning"
    assert derive_time_bucket("11:59") == "Morning"
    assert derive_time_bucket("12:00") == "Afternoon"
    assert derive_time_bucket("15:59") == "Afternoon"
    assert derive_time_bucket("16:00") == "Evening"
    assert derive_time_bucket("20:59") == "Evening"
    assert derive_time_bucket("21:00") == "Night"
    assert derive_time_bucket("23:30") == "Night"
    assert derive_time_bucket("00:30") == "Night"      # wraps midnight
    assert derive_time_bucket("04:59") == "Night"


def test_bucket_none_is_full_day():
    assert derive_time_bucket(None) == "Full Day"
    assert derive_time_bucket("") == "Full Day"
    assert derive_time_bucket("nonsense") == "Full Day"


def test_describe_time_buckets_matches_derive():
    rows = describe_time_buckets()
    assert [r["bucket"] for r in rows] == ["Morning", "Afternoon", "Evening", "Night"]
    by_bucket = {r["bucket"]: r for r in rows}
    assert (by_bucket["Morning"]["start"], by_bucket["Morning"]["end"]) == ("05:00", "12:00")
    assert (by_bucket["Afternoon"]["start"], by_bucket["Afternoon"]["end"]) == ("12:00", "16:00")
    assert (by_bucket["Evening"]["start"], by_bucket["Evening"]["end"]) == ("16:00", "21:00")
    assert (by_bucket["Night"]["start"], by_bucket["Night"]["end"]) == ("21:00", "05:00")
    assert [r["span_hours"] for r in rows] == [7, 4, 5, 8]
    # each row's own start time must derive back to that row's bucket
    for r in rows:
        assert derive_time_bucket(r["start"]) == r["bucket"]


def test_slot_span_hours():
    assert _slot_span_hours({"start_time": "07:00", "end_time": "14:00"}) == 7.0
    assert _slot_span_hours({"start_time": "16:00", "end_time": "23:00"}) == 7.0
    assert _slot_span_hours({"start_time": "22:00", "end_time": "06:00"}) == 8.0  # wraps midnight
    assert _slot_span_hours({"start_time": "09:00", "end_time": "09:00"}) == 24   # not 0
    assert _slot_span_hours({"start_time": "09:00", "end_time": None}) is None
    assert _slot_span_hours({"start_time": None, "end_time": "17:00"}) is None


def test_resolve_slot_bucket_precedence():
    assert resolve_slot_bucket({"start_time": "07:00"}) == "Morning"
    # explicit override wins over the derived value
    assert resolve_slot_bucket({"start_time": "07:00", "time_bucket": "Evening"}) == "Evening"
    # full-day hours label with no start time
    assert resolve_slot_bucket({"start_time": None, "hours_label": "Full Day"}) == "Full Day"
    # night-hourly slot
    assert resolve_slot_bucket({"start_time": "22:00", "is_night_hourly": 1}) == "Night"
    assert resolve_slot_bucket(None) is None


# --- compute_slot_charge --------------------------------------------------

def test_slot_charge_multiplies_by_plan_term():
    slot = {"monthly_fee": 1000, "is_night_hourly": 0}
    assert compute_slot_charge(slot, "Monthly") == 1000
    assert compute_slot_charge(slot, "Quarterly") == 3000
    assert compute_slot_charge(slot, "Half-Yearly") == 6000
    assert compute_slot_charge(slot, "Yearly") == 12000


def test_slot_charge_night_hourly():
    slot = {"night_hourly_rate": 20, "is_night_hourly": 1}
    assert compute_slot_charge(slot, "Monthly", night_hours=8) == 160


def test_slot_charge_custom_and_none():
    assert compute_slot_charge({"monthly_fee": 1000}, "Custom") is None
    assert compute_slot_charge(None, "Monthly") is None


def test_plan_months_map():
    assert PLAN_MONTHS == {"Monthly": 1, "Quarterly": 3, "Half-Yearly": 6, "Yearly": 12}


# --- waterfall ----------------------------------------------------------

def test_waterfall_fills_buckets_in_order():
    # ₹400 paid against reg 200 / deposit 300 / (rest) -> 200 to reg, 200 to deposit
    out = split_payment_across_buckets(
        [("Registration", 200), ("Deposit", 300), ("Membership", None)], 0, 400
    )
    assert out == [("Registration", 200.0), ("Deposit", 200.0), ("Membership", 0.0)]


def test_waterfall_respects_old_paid():
    # 200 already paid (covers registration); this 400 starts at the deposit bucket
    out = split_payment_across_buckets(
        [("Registration", 200), ("Deposit", 300), ("Membership", None)], 200, 400
    )
    assert out == [("Registration", 0.0), ("Deposit", 300.0), ("Membership", 100.0)]


def test_waterfall_shares_sum_to_amount():
    out = split_payment_across_buckets(
        [("A", 150), ("B", 250), ("C", 600)], 100, 700
    )
    assert round(sum(s for _, s in out), 6) == 700


def test_split_admission_wrapper_matches_old_formula():
    for old_paid, amount, af in [(0, 150, 200), (0, 500, 200), (100, 400, 200), (250, 50, 200)]:
        adm, mem = split_admission_and_membership_fee(af, old_paid, amount)
        exp_adm = min(old_paid + amount, af) - min(old_paid, af)
        assert adm == exp_adm
        assert adm + mem == amount


# --- get_charge_config --------------------------------------------------

def test_charge_config_defaults_when_no_settings():
    cfg = get_charge_config(None)
    assert [c["key"] for c in cfg] == [c["key"] for c in CHARGE_CATALOG]
    assert all(c["amount"] == 0 for c in cfg)
    by_key = {c["key"]: c for c in cfg}
    assert by_key["registration"]["compulsory"] is True
    assert by_key["security_deposit"]["compulsory"] is True
    assert by_key["seat_reservation"]["compulsory"] is False
    assert by_key["seat_reservation"]["recurring"] is True
    assert by_key["locker"]["recurring"] is True
    assert by_key["security_deposit"]["refundable"] is True


def test_charge_config_reads_settings_row():
    settings = {
        "admission_fee": 200,
        "seat_reservation_fee": 150,
        "locker_fee": 100,
        "security_deposit_amount": 500,
        "registration_compulsory": 0,
        "seat_reservation_compulsory": 1,
    }
    by_key = {c["key"]: c for c in get_charge_config(settings)}
    assert by_key["registration"]["amount"] == 200
    assert by_key["registration"]["compulsory"] is False
    assert by_key["seat_reservation"]["amount"] == 150
    assert by_key["seat_reservation"]["compulsory"] is True
    assert by_key["locker"]["amount"] == 100


# --- occupancy bucketing ----------------------------------------------

def test_membership_bucket_prefers_time_bucket_snapshot():
    assert _membership_bucket({"time_bucket": "Night", "shift": "MORNING"}) == "Night"
    assert _membership_bucket({"time_bucket": "Full Day"}) == FULL_DAY_LABEL
    # unknown snapshot value -> Other
    assert _membership_bucket({"time_bucket": "Whenever"}) == "Other"
    # no snapshot -> fall back to the student's free-text shift
    assert _membership_bucket({"shift": "EVENING"}) == "Evening"
    assert _membership_bucket({}) == "Other"


def test_night_is_a_canonical_shift():
    assert "Night" in CANONICAL_SHIFTS
    assert len(CANONICAL_SHIFTS) == 4
