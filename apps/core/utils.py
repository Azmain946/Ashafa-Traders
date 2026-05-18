"""Small shared helpers."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone


def money(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_date_range(range_key: str | None, today: date | None = None) -> tuple[date, date]:
    """Translate a UI range key into a (start, end) inclusive date pair."""
    today = today or timezone.localdate()
    key = (range_key or "today").lower()
    if key == "today":
        return today, today
    if key == "week":
        start = today - timedelta(days=today.weekday())
        return start, today
    if key == "month":
        return today.replace(day=1), today
    if key == "year":
        return today.replace(month=1, day=1), today
    if key == "yesterday":
        d = today - timedelta(days=1)
        return d, d
    return today, today


def date_or_none(raw):
    if not raw:
        return None
    if isinstance(raw, (date, datetime)):
        return raw if isinstance(raw, date) else raw.date()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
