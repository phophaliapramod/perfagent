"""Normalize ISO timestamps to naive UTC for DuckDB storage."""
from datetime import datetime, timezone
import math


def validate_window(service, start, end):
    if not isinstance(service, str) or not service.strip() or len(service) > 200:
        raise ValueError('Service must be a nonempty string of at most 200 characters.')
    def timestamp(value):
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError as exc:
                raise ValueError('Dates must be ISO-8601 timestamps.') from exc
        if not isinstance(value, datetime):
            raise ValueError('Dates must be datetime objects or ISO-8601 strings.')
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    start, end = timestamp(start), timestamp(end)
    if end <= start:
        raise ValueError('End must be after start (end is exclusive).')
    return service, start, end


def validate_threshold(value, name, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{name} must be a finite nonnegative number.')
    if maximum is not None and value > maximum:
        raise ValueError(f'{name} must be at most {maximum}.')
    return value
