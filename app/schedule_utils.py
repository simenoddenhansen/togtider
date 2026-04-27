"""
Utilities for working with the scraper schedule.
"""

from datetime import timedelta

SCRAPE_INTERVAL_MINUTES = 10
SCRAPE_INTERVAL_SECONDS = SCRAPE_INTERVAL_MINUTES * 60


def get_next_scheduled_update(dt):
    """
    Return the next scheduled scraper run after ``dt`` on a 10-minute cadence.

    The cadence is anchored to midnight local time:
    00:00, 00:10, 00:20, 00:30, ...
    """
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_seconds = int((dt - midnight).total_seconds())
    next_elapsed = ((elapsed_seconds // SCRAPE_INTERVAL_SECONDS) + 1) * SCRAPE_INTERVAL_SECONDS
    return midnight + timedelta(seconds=next_elapsed)
