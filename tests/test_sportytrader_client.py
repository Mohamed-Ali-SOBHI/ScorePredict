from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from inference.sportytrader_client import (
    KickoffTimeVerificationError,
    apply_structured_fixture_times,
    fetch_upcoming_league_fixtures,
    fetch_upcoming_fixtures_for_leagues,
    parse_fixture_timestamp,
    parse_upcoming_fixtures,
    parse_structured_fixture_times,
    parse_sportsdb_fixture_times,
)


class SportyTraderClientTests(unittest.TestCase):
    def test_september_label_does_not_stop_the_fixture_list(self) -> None:
        fixtures = parse_upcoming_fixtures(
            """Upcoming Premier League matches
31 Aug - 21:00
Aston Villa - Arsenal
1
6.8
X
4.5
2
1.56
04 Sept - 21:00
Ipswich Town - Liverpool
1
5.25
X
4.47
2
1.68
05 Sept - 13:30
Newcastle - Bournemouth
1
2.36
X
3.81
2
3.04
""",
            date_from=pd.Timestamp("2026-08-30"),
            date_to=pd.Timestamp("2026-09-20"),
            league="EPL",
        )

        self.assertEqual(len(fixtures), 3)
        self.assertEqual(fixtures.iloc[1]["date"], pd.Timestamp("2026-09-04 21:00:00"))

    def test_french_month_labels_remain_supported(self) -> None:
        self.assertEqual(
            parse_fixture_timestamp("04 sept. - 21:00", pd.Timestamp("2026-08-30")),
            pd.Timestamp("2026-09-04 21:00:00"),
        )
        self.assertEqual(
            parse_fixture_timestamp("31 août - 21:00", pd.Timestamp("2026-08-30")),
            pd.Timestamp("2026-08-31 21:00:00"),
        )

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

    @staticmethod
    def _structured_event() -> list[dict[str, object]]:
        return [
            {
                "@type": "SportsEvent",
                "url": "https://www.sportytrader.com/en/odds/ipswich-sunderland-8595825/",
                "startDate": "2026-08-22T14:00:00+00:00",
                "homeTeam": {"name": "Ipswich Town"},
                "awayTeam": {"name": "Sunderland"},
            }
        ]

    def test_jsonld_utc_time_is_canonical_and_has_a_stable_id(self) -> None:
        canonical = parse_structured_fixture_times(self._structured_event(), league="EPL")

        self.assertEqual(canonical.iloc[0]["fixture_id"], "sportytrader:8595825")
        self.assertEqual(canonical.iloc[0]["official_date"], pd.Timestamp("2026-08-22 16:00:00"))
        self.assertEqual(canonical.iloc[0]["kickoff_utc"], "2026-08-22T14:00:00+00:00")

    def test_visible_server_time_is_replaced_by_jsonld_utc_time(self) -> None:
        canonical = parse_structured_fixture_times(self._structured_event(), league="EPL")
        corrected = apply_structured_fixture_times(self._scraped_fixture().iloc[[0]], canonical)

        self.assertEqual(corrected.iloc[0]["date"], pd.Timestamp("2026-08-22 16:00:00"))
        self.assertEqual(
            corrected.iloc[0]["source"],
            "sportytrader_playwright+sportytrader_jsonld_utc",
        )

    def test_sportsdb_utc_time_is_still_available_for_final_results(self) -> None:
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
        self.assertEqual(official.iloc[0]["official_date"], pd.Timestamp("2026-08-22 16:00:00"))

    def test_refuses_a_visible_time_without_its_canonical_event(self) -> None:
        canonical = parse_structured_fixture_times(self._structured_event(), league="EPL")

        with self.assertRaisesRegex(KickoffTimeVerificationError, "Canonical UTC kickoff missing"):
            apply_structured_fixture_times(self._scraped_fixture(), canonical)

    @patch("inference.sportytrader_client.fetch_upcoming_league_fixtures")
    def test_partial_catalog_skips_only_the_unverifiable_league(self, fetch_league) -> None:
        def fake_fetch(league: str, **kwargs) -> pd.DataFrame:
            if league == "La_liga":
                from inference.sportytrader_client import KickoffTimeVerificationError

                raise KickoffTimeVerificationError("official schedule is delayed")
            frame = pd.DataFrame(
                [
                    {
                        "date": pd.Timestamp("2026-08-29 16:00:00"),
                        "league": league,
                        "home_team": "Home",
                        "away_team": "Away",
                        "source": "test",
                    }
                ]
            )
            offset = 360 if league == "EPL" else 420
            frame.attrs["verified_offset_minutes_by_league"] = {league: offset}
            return frame

        fetch_league.side_effect = fake_fetch

        fixtures = fetch_upcoming_fixtures_for_leagues(
            ["EPL", "Serie_A", "La_liga"],
            date_from=pd.Timestamp("2026-08-26"),
            date_to=pd.Timestamp("2026-09-16"),
            wait_seconds=0,
            timeout_seconds=1,
            allow_partial=True,
        )

        self.assertEqual(set(fixtures["league"]), {"EPL", "Serie_A"})

    @patch("inference.sportytrader_client.fetch_league_page_payload")
    def test_fetch_uses_jsonld_without_a_second_schedule_source(self, fetch_page) -> None:
        fetch_page.return_value = {
            "title": "LaLiga odds",
            "pageText": """Upcoming LaLiga matches
25 Aug - 10:00
Home - Away
1
2.0
X
3.5
2
4.0
""",
            "sportsEvents": [
                {
                    "@type": "SportsEvent",
                    "url": "https://www.sportytrader.com/en/odds/home-away-12345/",
                    "startDate": "2026-08-25T14:00:00+00:00",
                    "homeTeam": {"name": "Home"},
                    "awayTeam": {"name": "Away"},
                }
            ],
        }

        fixtures = fetch_upcoming_league_fixtures(
            "La_liga",
            date_from=pd.Timestamp("2026-08-24"),
            date_to=pd.Timestamp("2026-09-14"),
            wait_seconds=0,
            timeout_seconds=1,
        )

        self.assertEqual(fetch_page.call_count, 1)
        self.assertEqual(fixtures.iloc[0]["date"], pd.Timestamp("2026-08-25 16:00:00"))
        self.assertEqual(fixtures.iloc[0]["fixture_id"], "sportytrader:12345")


if __name__ == "__main__":
    unittest.main()
