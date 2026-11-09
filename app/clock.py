"""Single source of 'now' so tests can freeze time.

All times in the DB are naive clinic-local datetimes (America/New_York by default).
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config


def now() -> datetime:
    return datetime.now(ZoneInfo(config.CLINIC_TZ)).replace(tzinfo=None, second=0, microsecond=0)
