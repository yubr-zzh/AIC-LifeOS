"""Deterministic date-period resolution for historical memory retrieval."""

import re
from datetime import datetime, timedelta, timezone


def resolve_as_of(query: str, reference_time: datetime | None = None) -> datetime | None:
    """Return the UTC end of an explicitly requested period, if recognized."""
    reference_time = reference_time or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    year = reference_time.year
    text = query or ""
    match = re.search(r"(去年|前年|今年)?\s*(\d{4})?\s*年?\s*(上半年|下半年|第一季度|第二季度|第三季度|第四季度|Q[1-4])", text, re.I)
    if match:
        relative, explicit_year, period = match.groups()
        target_year = int(explicit_year) if explicit_year else year - (2 if relative == "前年" else 1 if relative == "去年" else 0)
        period = period.upper()
        if period == "上半年": month, day = 6, 30
        elif period == "下半年": month, day = 12, 31
        else:
            quarter = (
                int(period[1])
                if period.startswith("Q")
                else {"一": 1, "二": 2, "三": 3, "四": 4}[period[1]]
            )
            month = quarter * 3
            day = (datetime(target_year, month + 1, 1) - timedelta(days=1)).day if month < 12 else 31
        return datetime(target_year, month, day, 23, 59, 59, tzinfo=timezone.utc)
    match = re.search(r"(去年|前年|今年)?\s*(\d{4})?\s*年\s*(\d{1,2})\s*月", text)
    if match:
        relative, explicit_year, raw_month = match.groups()
        target_year = int(explicit_year) if explicit_year else year - (2 if relative == "前年" else 1 if relative == "去年" else 0)
        month = int(raw_month)
        if not 1 <= month <= 12:
            return None
        next_month = datetime(target_year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
        return next_month - timedelta(seconds=1)
    return None
