"""Soft weekend sync reminder (Europe/Copenhagen, Danish text).

Rule: on Saturday and Sunday (Copenhagen local date) the reminder is active
when there has been no sync on Thursday, Friday or Saturday of the same ISO
week (Mon–Sun). A sync on the Sunday itself also counts. On Monday–Friday
there is never a reminder. The reminder is a friendly, non-invasive nudge:
a calm info chip on the card + binary_sensor/attributes for automations.
No persistent_notification, no repair issue, no push.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

CPH_TZ = ZoneInfo("Europe/Copenhagen")
THURSDAY = 3
SATURDAY = 5
SUNDAY = 6


def _local_date(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(CPH_TZ).date()


def parse_last_sync(value: Any) -> datetime | None:
    """Parse a stored ISO timestamp (naive values are treated as UTC)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def days_since_sync(last_sync: datetime | None, now: datetime) -> int | None:
    """Whole Copenhagen calendar days between the last sync and now."""
    if last_sync is None:
        return None
    return max(0, (_local_date(now) - _local_date(last_sync)).days)


def reminder_short(days: int | None) -> str:
    """Short form for automations / compact UIs."""
    if days is None:
        return "Ikke synkroniseret endnu"
    if days == 1:
        return "Ikke synkroniseret i 1 dag"
    return f"Ikke synkroniseret i {days} dage"


def reminder_message(days: int | None) -> str:
    """Friendly, non-invasive nudge shown on the card (no push, no repair)."""
    if days is None:
        return "Der er ikke synkroniseret endnu — tryk Synkroniser, når du har et øjeblik."
    if days == 1:
        return "Det er 1 dag siden sidste synkronisering — tryk Synkroniser, når du har et øjeblik."
    return f"Det er {days} dage siden sidste synkronisering — tryk Synkroniser, når du har et øjeblik."


def is_reminder_due(last_sync: datetime | None, now: datetime) -> bool:
    """True on Sat/Sun when no sync happened Thu–Sat (or the Sunday itself) this week."""
    today = _local_date(now)
    if today.weekday() not in (SATURDAY, SUNDAY):
        return False
    if last_sync is None:
        return True
    last = _local_date(last_sync)
    thursday = today - timedelta(days=today.weekday() - THURSDAY)
    return last < thursday


def compute_sync_reminder(
    last_sync: datetime | None, now: datetime, enabled: bool = True
) -> dict[str, Any]:
    """Attributes for the card, the overview sensor and the binary_sensor."""
    days = days_since_sync(last_sync, now)
    due = bool(enabled) and is_reminder_due(last_sync, now)
    return {
        "last_sync": last_sync.isoformat(timespec="seconds") if last_sync else None,
        "days_since_sync": days,
        "sync_reminder": due,
        "sync_reminder_message": reminder_message(days) if due else "",
        "sync_reminder_short": reminder_short(days) if due else "",
        "sync_reminder_enabled": bool(enabled),
    }
