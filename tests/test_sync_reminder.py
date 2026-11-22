"""Soft weekend sync reminder: Sat/Sun only, unless synced Thu, Fri, Sat (or that Sunday)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from kmd_easy_energy.sync_reminder import (
    compute_sync_reminder,
    days_since_sync,
    is_reminder_due,
    parse_last_sync,
    reminder_message,
)

CPH = ZoneInfo("Europe/Copenhagen")


def cph(y: int, m: int, d: int, h: int = 12, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=CPH)


# Week of Mon 16 Nov 2026 .. Sun 22 Nov 2026
MON, TUE, WED, THU, FRI, SAT, SUN = (cph(2026, 11, d) for d in range(16, 23))


def test_calendar_anchor() -> None:
    assert [d.weekday() for d in (MON, TUE, WED, THU, FRI, SAT, SUN)] == list(range(7))


@pytest.mark.parametrize("today", [MON, TUE, WED, THU, FRI])
@pytest.mark.parametrize("last", [None, cph(2026, 10, 1), cph(2026, 11, 9)])
def test_never_on_weekdays(today: datetime, last: datetime | None) -> None:
    assert is_reminder_due(last, today) is False
    rem = compute_sync_reminder(last, today)
    assert rem["sync_reminder"] is False
    assert rem["sync_reminder_message"] == ""


@pytest.mark.parametrize("today", [SAT, SUN])
@pytest.mark.parametrize("last", [THU, FRI, cph(2026, 11, 19, 0, 1), cph(2026, 11, 20, 23, 59)])
def test_no_reminder_when_synced_thursday_or_friday(today: datetime, last: datetime) -> None:
    assert is_reminder_due(last, today) is False


def test_no_reminder_when_synced_saturday() -> None:
    assert is_reminder_due(cph(2026, 11, 21, 8), SAT.replace(hour=20)) is False
    assert is_reminder_due(cph(2026, 11, 21, 8), SUN) is False


def test_sunday_sync_clears_sunday_reminder() -> None:
    last = WED
    before = cph(2026, 11, 22, 9)
    assert is_reminder_due(last, before) is True
    synced_sunday = cph(2026, 11, 22, 10)
    assert is_reminder_due(synced_sunday, cph(2026, 11, 22, 18)) is False


@pytest.mark.parametrize("today", [SAT, SUN])
@pytest.mark.parametrize("last", [MON, TUE, WED, cph(2026, 11, 18, 23, 59)])
def test_reminder_when_last_sync_before_thursday(today: datetime, last: datetime) -> None:
    assert is_reminder_due(last, today) is True


def test_previous_weekend_sync_does_not_count_for_this_week() -> None:
    last_sunday = cph(2026, 11, 15, 20)  # previous week's Sunday
    assert is_reminder_due(last_sunday, SAT) is True
    assert days_since_sync(last_sunday, SAT) == 6
    assert compute_sync_reminder(last_sunday, SAT)["sync_reminder_message"] == "Det er 6 dage siden sidste synkronisering — tryk Synkroniser, når du har et øjeblik."


def test_reminder_resets_on_monday() -> None:
    assert is_reminder_due(WED, SUN) is True
    assert is_reminder_due(WED, cph(2026, 11, 23, 0, 0)) is False  # Monday


def test_never_synced_weekend_vs_weekday() -> None:
    rem = compute_sync_reminder(None, SAT)
    assert rem["sync_reminder"] is True
    assert rem["days_since_sync"] is None
    assert rem["sync_reminder_message"].startswith("Der er ikke synkroniseret endnu")
    assert rem["sync_reminder_short"] == "Ikke synkroniseret endnu"
    assert compute_sync_reminder(None, FRI)["sync_reminder"] is False


def test_message_counts_copenhagen_calendar_days() -> None:
    rem = compute_sync_reminder(TUE, SAT)
    assert rem["days_since_sync"] == 4
    assert rem["sync_reminder_message"] == "Det er 4 dage siden sidste synkronisering — tryk Synkroniser, når du har et øjeblik."
    assert reminder_message(1).startswith("Det er 1 dag siden")
    assert rem["sync_reminder_short"] == "Ikke synkroniseret i 4 dage"


def test_disabled_option_never_reminds() -> None:
    rem = compute_sync_reminder(MON, SAT, enabled=False)
    assert rem["sync_reminder"] is False
    assert rem["sync_reminder_message"] == ""
    assert rem["sync_reminder_enabled"] is False
    assert rem["days_since_sync"] == 5  # still exposed for automations


def test_utc_inputs_use_copenhagen_date_boundaries() -> None:
    # Wed 18 Nov 23:30 UTC == Thu 19 Nov 00:30 Copenhagen -> counts as Thursday.
    last = datetime(2026, 11, 18, 23, 30, tzinfo=timezone.utc)
    sat_utc = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    assert is_reminder_due(last, sat_utc) is False
    # Fri 20 Nov 23:30 UTC == Sat 21 Nov 00:30 Copenhagen: "now" is already Saturday.
    now = datetime(2026, 11, 20, 23, 30, tzinfo=timezone.utc)
    assert is_reminder_due(cph(2026, 11, 17), now) is True
    # Sun 22 Nov 23:30 UTC == Mon 23 Nov in Copenhagen -> no reminder.
    assert is_reminder_due(cph(2026, 11, 17), datetime(2026, 11, 22, 23, 30, tzinfo=timezone.utc)) is False


def test_dst_end_weekend_october() -> None:
    # DST ends Sun 25 Oct 2026 03:00 CEST -> 02:00 CET.
    thu = cph(2026, 10, 22, 21)
    sat = cph(2026, 10, 24, 12)
    sun_after_switch = cph(2026, 10, 25, 23, 30)
    assert is_reminder_due(thu, sat) is False
    assert is_reminder_due(thu, sun_after_switch) is False
    wed = cph(2026, 10, 21, 22)
    assert is_reminder_due(wed, sun_after_switch) is True
    assert days_since_sync(wed, sun_after_switch) == 4
    # Late Sunday in UTC is still Sunday locally after the switch (UTC+1).
    assert is_reminder_due(wed, datetime(2026, 10, 25, 22, 30, tzinfo=timezone.utc)) is True


def test_dst_start_weekend_march() -> None:
    # DST starts Sun 29 Mar 2026 02:00 CET -> 03:00 CEST.
    fri = cph(2026, 3, 27, 23, 59)
    sun = cph(2026, 3, 29, 12)
    assert is_reminder_due(fri, sun) is False
    tue = cph(2026, 3, 24, 8)
    assert is_reminder_due(tue, sun) is True
    assert days_since_sync(tue, sun) == 5
    # 21:59 UTC on Sunday is 23:59 CEST, still Sunday.
    assert is_reminder_due(tue, datetime(2026, 3, 29, 21, 59, tzinfo=timezone.utc)) is True
    # 22:00 UTC is Monday 00:00 CEST -> no reminder.
    assert is_reminder_due(tue, datetime(2026, 3, 29, 22, 0, tzinfo=timezone.utc)) is False


def test_year_boundary_week() -> None:
    # Thu 31 Dec 2026, Sat 2 Jan 2027 (same Mon-Sun week).
    assert is_reminder_due(cph(2026, 12, 31), cph(2027, 1, 2)) is False
    assert is_reminder_due(cph(2026, 12, 30), cph(2027, 1, 3)) is True


def test_future_last_sync_is_not_a_reminder() -> None:
    assert is_reminder_due(SAT + timedelta(days=3), SAT) is False
    assert days_since_sync(SAT + timedelta(days=3), SAT) == 0


def test_parse_last_sync_variants() -> None:
    assert parse_last_sync(None) is None
    assert parse_last_sync("") is None
    assert parse_last_sync("garbage") is None
    naive = parse_last_sync("2026-11-19T10:00:00")
    assert naive is not None and naive.tzinfo is not None  # treated as UTC
    z = parse_last_sync("2026-11-19T10:00:00Z")
    assert z == datetime(2026, 11, 19, 10, tzinfo=timezone.utc)
    off = parse_last_sync("2026-11-19T10:00:00+01:00")
    assert off.utcoffset() == timedelta(hours=1)


def test_compute_exposes_iso_last_sync() -> None:
    rem = compute_sync_reminder(THU, SAT)
    assert rem["last_sync"].startswith("2026-11-19T12:00:00")
    assert rem["sync_reminder_enabled"] is True


def test_wording_is_friendly_not_alarming() -> None:
    for days in (None, 1, 2, 9):
        msg = reminder_message(days)
        assert "når du har et øjeblik" in msg
        for word in ("Fejl", "fejl", "Advarsel", "⚠", "!"):
            assert word not in msg
