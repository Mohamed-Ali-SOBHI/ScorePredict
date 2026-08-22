from __future__ import annotations

import unittest

import pandas as pd

from inference.sportytrader_client import (
    parse_sportsdb_fixture_times,
    reconcile_fixture_times,
)


class SportyTraderClientTests(unittest.TestCase):
    @staticmethod
    def _scraped_fixture() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-08-22 10:00:00"),
                    "league": "EPL",
                    "home_team": "Ipswich Town",
                    "away_team": "Sunderland",
                    "home_win_odds_open": 2.85,
                    "draw_odds_open": 3.5,
                    "away_win_odds_open": 2.69,
                    "source": "sportytrader_playwright",
                },
                {
                    "date": pd.Timestamp("2026-08-23 09:00:00"),
                    "league": "EPL",
                    "home_team": "Unlisted United",
                    "away_team": "Missing City",
                    "home_win_odds_open": 2.5,
                    "draw_odds_open": 3.2,
                    "away_win_odds_open": 2.8,
                    "source": "sportytrader_playwright",
                }
            ]
        )

    def test_sportsdb_utc_time_is_converted_to_paris_summer_time(self) -> None:
        payload = {
            "events": [
                {
                    "strTimestamp": "2026-08-22T14:00:00",
                    "strHomeTeam": "Ipswich Town",
                    "strAwayTeam": "Sunderland",
                }
            ]
        }

        official = parse_sportsdb_fixture_times(payload, league="EPL")
        corrected = reconcile_fixture_times(self._scraped_fixture(), official)

        self.assertEqual(corrected.iloc[0]["date"], pd.Timestamp("2026-08-22 16:00:00"))
        self.assertEqual(corrected.iloc[1]["date"], pd.Timestamp("2026-08-23 15:00:00"))
        self.assertEqual(corrected.iloc[0]["source"], "sportytrader_playwright+sportsdb_timezone")

    def test_refuses_to_publish_an_unverified_kickoff_time(self) -> None:
        official = pd.DataFrame(
            columns=["league", "home_team_norm", "away_team_norm", "official_date"]
        )

        with self.assertRaisesRegex(ValueError, "Unable to verify"):
            reconcile_fixture_times(self._scraped_fixture(), official)


if __name__ == "__main__":
    unittest.main()
