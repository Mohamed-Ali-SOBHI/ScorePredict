from __future__ import annotations

import unittest

import pandas as pd

from inference.kickoff_time import paris_date_key, paris_iso, paris_naive, paris_timestamp


class KickoffTimeTests(unittest.TestCase):
    def test_naive_kickoff_is_always_interpreted_as_paris_local_time(self) -> None:
        kickoff = paris_timestamp("2026-08-29 15:30:00")

        self.assertEqual(kickoff.hour, 15)
        self.assertEqual(kickoff.utcoffset(), pd.Timedelta(hours=2))
        self.assertEqual(paris_iso(kickoff), "2026-08-29T15:30:00+02:00")

    def test_utc_kickoff_is_converted_to_the_same_paris_instant(self) -> None:
        self.assertEqual(paris_naive("2026-08-29T13:30:00Z"), pd.Timestamp("2026-08-29 15:30:00"))

    def test_local_date_key_never_slips_to_the_previous_utc_day(self) -> None:
        self.assertEqual(paris_date_key("2026-08-29T00:30:00+02:00"), "2026-08-29")
