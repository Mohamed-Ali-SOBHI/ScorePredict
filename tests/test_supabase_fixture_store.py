from __future__ import annotations

import unittest

import pandas as pd

from inference.supabase_fixture_store import fixture_records


class SupabaseFixtureStoreTests(unittest.TestCase):
    def test_builds_a_canonical_utc_fixture_record(self) -> None:
        records = fixture_records(
            pd.DataFrame(
                [
                    {
                        "fixture_id": "sportytrader:8595825",
                        "league": "Bundesliga",
                        "home_team": "Augsburg",
                        "away_team": "Schalke 04",
                        "kickoff_utc": "2026-08-30T15:30:00+00:00",
                        "home_win_odds_open": 2.28,
                        "draw_odds_open": 3.9,
                        "away_win_odds_open": 3.35,
                        "schedule_source": "sportytrader_jsonld_utc",
                        "source": "sportytrader_playwright+sportytrader_jsonld_utc",
                    }
                ]
            )
        )

        self.assertEqual(records[0]["fixture_id"], "sportytrader:8595825")
        self.assertEqual(records[0]["kickoff_utc"], "2026-08-30T15:30:00+00:00")
        self.assertEqual(records[0]["season"], 2026)
        self.assertEqual(records[0]["draw_odds_open"], 3.9)
        self.assertIn("updated_at", records[0])


if __name__ == "__main__":
    unittest.main()
