from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from inference.sportytrader_client import (
    fetch_upcoming_fixtures_for_leagues,
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

    def test_accepts_an_offset_verified_on_another_league_page(self) -> None:
        official = pd.DataFrame(
            columns=["league", "home_team_norm", "away_team_norm", "official_date"]
        )

        corrected = reconcile_fixture_times(
            self._scraped_fixture(),
            official,
            fallback_offset_minutes=360,
        )

        self.assertEqual(corrected.iloc[0]["date"], pd.Timestamp("2026-08-22 16:00:00"))
        self.assertEqual(
            corrected.iloc[0]["source"],
            "sportytrader_playwright+shared_verified_timezone",
        )

    @patch("inference.sportytrader_client.fetch_upcoming_league_fixtures")
    def test_retries_a_league_with_the_shared_verified_offset(self, fetch_league) -> None:
        def fake_fetch(league: str, **kwargs) -> pd.DataFrame:
            fallback = kwargs.get("fallback_offset_minutes")
            if league == "La_liga" and fallback is None:
                from inference.sportytrader_client import KickoffTimeVerificationError

                raise KickoffTimeVerificationError("Unable to verify La_liga")
            frame = pd.DataFrame(
                [
                    {
                        "date": pd.Timestamp("2026-08-25 16:00:00"),
                        "league": league,
                        "home_team": "Home",
                        "away_team": "Away",
                        "source": "test",
                    }
                ]
            )
            frame.attrs["verified_offset_minutes_by_league"] = {league: fallback or 360}
            return frame

        fetch_league.side_effect = fake_fetch

        fixtures = fetch_upcoming_fixtures_for_leagues(
            ["EPL", "La_liga"],
            date_from=pd.Timestamp("2026-08-24"),
            date_to=pd.Timestamp("2026-09-14"),
            wait_seconds=0,
            timeout_seconds=1,
        )

        self.assertEqual(set(fixtures["league"]), {"EPL", "La_liga"})
        retry = [
            call
            for call in fetch_league.call_args_list
            if call.args[0] == "La_liga"
            and call.kwargs.get("fallback_offset_minutes") == 360
        ]
        self.assertEqual(len(retry), 1)

    @patch("inference.sportytrader_client.fetch_sportsdb_fixture_times")
    @patch("inference.sportytrader_client.fetch_league_page_text")
    def test_shared_offset_retry_reuses_the_first_download(
        self,
        fetch_page,
        fetch_official,
    ) -> None:
        fetch_page.return_value = """Upcoming LaLiga matches
25 Aug - 10:00
Home - Away
1
2.0
X
3.5
2
4.0
"""
        fetch_official.return_value = pd.DataFrame(
            columns=["league", "home_team_norm", "away_team_norm", "official_date"]
        )
        source_cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}

        with self.assertRaisesRegex(ValueError, "Unable to verify"):
            from inference.sportytrader_client import fetch_upcoming_league_fixtures

            fetch_upcoming_league_fixtures(
                "La_liga",
                date_from=pd.Timestamp("2026-08-24"),
                date_to=pd.Timestamp("2026-09-14"),
                wait_seconds=0,
                timeout_seconds=1,
                _source_cache=source_cache,
            )

        corrected = fetch_upcoming_league_fixtures(
            "La_liga",
            date_from=pd.Timestamp("2026-08-24"),
            date_to=pd.Timestamp("2026-09-14"),
            wait_seconds=0,
            timeout_seconds=1,
            fallback_offset_minutes=360,
            _source_cache=source_cache,
        )

        self.assertEqual(fetch_page.call_count, 1)
        self.assertEqual(fetch_official.call_count, 1)
        self.assertEqual(corrected.iloc[0]["date"], pd.Timestamp("2026-08-25 16:00:00"))


if __name__ == "__main__":
    unittest.main()
