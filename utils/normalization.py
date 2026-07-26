"""
Centralized input normalization.

Every record must be stored in a consistent format so analytics, searching,
reporting, and filtering are always accurate - two admins typing "upsc",
"Upsc" and "UPSC" must land in the same bucket. This module is the single
place that decides what "consistent" means for each kind of field; routes
must call these helpers instead of writing their own .upper()/.title()
logic (see docs/DECISIONS.md for the ADR).

Four field families, four rules:
  * Category fields (Purpose, Shift, Membership Plan, Payment Mode)
    -> UPPERCASE (normalize_category)
  * Person name fields (Student/Father/Mother/Guardian/Emergency Contact
    Name, Owner Name) -> Title Case (normalize_name)
  * Location fields (City, State, ...) -> Title Case (normalize_location,
    same rule as names, kept as a distinct name for call-site clarity)
  * Free text (Address, Remarks, Notes, Descriptions) -> whitespace
    trimmed/collapsed only, casing untouched (normalize_free_text)
  * Phone numbers -> whitespace trimmed/collapsed only (normalize_phone)
"""

import re

_WHITESPACE_RE = re.compile(r"\s+")
_ALPHA_RUN_RE = re.compile(r"[A-Za-z]+")


def collapse_whitespace(value):
    """Trim leading/trailing whitespace and collapse internal runs of
    whitespace into a single space. None/blank input returns ""."""
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", value.strip())


def normalize_category(value):
    """Category fields (Purpose, Shift, Membership Plan, Payment Mode):
    'upsc'/'Upsc'/'UPSC' all become 'UPSC', so a single value can never be
    split into multiple buckets by capitalization alone."""
    return collapse_whitespace(value).upper()


def normalize_name(value):
    """Person name fields: 'RAHUL VERMA' / 'rahul verma' both become
    'Rahul Verma'. Only ASCII letter runs are re-cased, so non-Latin
    scripts (Devanagari, CJK, ...) and emoji pass through untouched."""
    text = collapse_whitespace(value)
    return _ALPHA_RUN_RE.sub(lambda m: m.group(0).capitalize(), text)


def normalize_location(value):
    """Location fields (City, State, ...): same Title Case rule as person
    names - 'new delhi' -> 'New Delhi'."""
    return normalize_name(value)


def normalize_free_text(value):
    """Free text fields (Address, Remarks, Notes, Descriptions): only
    whitespace is trimmed/collapsed - the user's own capitalization is
    preserved exactly."""
    return collapse_whitespace(value)


def normalize_phone(value):
    """Phone numbers: leading/trailing whitespace trimmed, digits left
    untouched."""
    return collapse_whitespace(value)
