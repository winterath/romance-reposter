from __future__ import annotations

import random
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import AppConfig

DAY_INDEX = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def next_schedule_times(config: AppConfig, count: int) -> list[str]:
    """Generate randomized UTC schedule timestamps inside configured windows."""

    timezone_name = config.get("app.timezone", "America/Chicago")
    tz = ZoneInfo(timezone_name)
    windows = config.get("posting.schedule_windows", [])
    min_gap = timedelta(minutes=int(config.get("posting.min_minutes_between_posts", 90)))
    cursor = datetime.now(tz)
    scheduled: list[datetime] = []

    while len(scheduled) < count:
        candidate = _next_window_time(cursor, windows, tz)
        if scheduled and candidate < scheduled[-1] + min_gap:
            cursor = scheduled[-1] + min_gap
            continue
        scheduled.append(candidate)
        cursor = candidate + min_gap

    return [item.astimezone(timezone.utc).replace(microsecond=0).isoformat() for item in scheduled]


def _next_window_time(cursor: datetime, windows: list[dict], tz: ZoneInfo) -> datetime:
    for day_offset in range(14):
        day = (cursor + timedelta(days=day_offset)).date()
        weekday = day.weekday()
        for window in windows:
            allowed_days = {DAY_INDEX[item.lower()] for item in window.get("days", [])}
            if allowed_days and weekday not in allowed_days:
                continue
            start = _parse_time(window["start"])
            end = _parse_time(window["end"])
            start_dt = datetime.combine(day, start, tz)
            end_dt = datetime.combine(day, end, tz)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
            lower = max(cursor, start_dt)
            if lower <= end_dt:
                span_seconds = max(0, int((end_dt - lower).total_seconds()))
                return lower + timedelta(seconds=random.randint(0, span_seconds))
    return cursor + timedelta(hours=24)


def _parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))
