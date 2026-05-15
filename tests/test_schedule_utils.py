import os
import sys
import unittest
from datetime import datetime


APP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app")
sys.path.insert(0, APP_DIR)

from schedule_utils import SCRAPE_INTERVAL_MINUTES, get_next_scheduled_update


class ScheduleUtilsTest(unittest.TestCase):
    def test_published_update_interval_is_hourly(self):
        self.assertEqual(SCRAPE_INTERVAL_MINUTES, 60)

    def test_next_update_uses_hourly_cadence(self):
        current = datetime(2026, 5, 15, 10, 11, 0)

        self.assertEqual(
            get_next_scheduled_update(current),
            datetime(2026, 5, 15, 11, 0, 0),
        )


if __name__ == "__main__":
    unittest.main()
