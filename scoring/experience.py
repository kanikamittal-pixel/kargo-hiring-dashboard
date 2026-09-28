from __future__ import annotations

import re
from datetime import date


def _parse_month_year(s: str, reference_date: date) -> date:
    s = s.strip()
    if s.lower() == "present":
        return reference_date
    for fmt in ("%b %Y", "%B %Y", "%Y-%m", "%Y-%m-%d", "%m/%Y"):
        try:
            from datetime import datetime
            parsed = datetime.strptime(s, fmt)
            return date(parsed.year, parsed.month, 1)
        except ValueError:
            continue
    match = re.search(r"(\d{4})", s)
    if match:
        return date(int(match.group(1)), 1, 1)
    raise ValueError(f"Could not parse date: {s!r}")


def years_pm_experience(roles: list[dict], reference_date: date) -> float:
    """Sum the duration (in years) of every role flagged is_product_management_role.
    Overlapping PM roles are merged so overlap is not double-counted."""
    intervals = []
    for role in roles:
        if not role.get("is_product_management_role"):
            continue
        try:
            start = _parse_month_year(role["start"], reference_date)
            end = _parse_month_year(role["end"], reference_date)
        except (ValueError, KeyError):
            continue
        if end < start:
            continue
        intervals.append((start, min(end, reference_date)))

    if not intervals:
        return 0.0

    intervals.sort()
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    total_days = sum((end - start).days for start, end in merged)
    return round(total_days / 365.25, 2)
