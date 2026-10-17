import unittest
from datetime import datetime, timezone

from inference.results_watch import monitor_busy, watch_state


class ResultsWatchTests(unittest.TestCase):
    def state(self, hour, minute=0, status="pending"):
        return watch_state({"activity": [{"date": "2026-10-17T15:30:00+02:00",
            "recommended": True, "status": status}]}, datetime(2026, 10, 17, hour, minute, tzinfo=timezone.utc))

    def test_waits_without_dispatch_before_the_result_window(self):
        self.assertEqual(self.state(12), (True, False))
        self.assertEqual(self.state(15, 14), (True, False))
        self.assertEqual(self.state(15, 15), (True, True))

    def test_no_runner_kept_alive_for_settled_or_old_matches(self):
        self.assertEqual(self.state(16, status="won"), (False, False))
        self.assertEqual(self.state(20), (False, False))
        self.assertEqual(self.state(5), (False, False))
        self.assertEqual(watch_state({}, datetime.now(timezone.utc)), (False, False))

    def test_unmatched_is_retried_and_queued_run_is_not_duplicated(self):
        self.assertEqual(self.state(16, status="unmatched"), (True, True))
        self.assertTrue(monitor_busy([{"status": "pending"}]))
        self.assertTrue(monitor_busy([{"status": "in_progress"}]))
        self.assertFalse(monitor_busy([{"status": "completed"}]))
