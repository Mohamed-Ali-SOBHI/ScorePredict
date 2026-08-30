from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from inference.live_tracking import (
    append_tracking_rows,
    build_tracking_rows,
    refresh_pending_fixture_dates_from_catalog,
)


class LiveTrackingTests(unittest.TestCase):
    def test_fixture_catalog_repairs_a_published_bet_even_when_not_recommended_again(self) -> None:
        ledger = pd.DataFrame(
            [
                {
                    "date": "2026-08-29T07:30:00+02:00",
                    "league": "Bundesliga",
                    "team_name": "Spvgg Elversberg",
                    "opponent_name": "Bayer Leverkusen",
                    "result_status": "pending_data_refresh",
                }
            ]
        )
        fixtures = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-08-29 15:30:00"),
                    "fixture_id": "sportytrader:123",
                    "kickoff_utc": "2026-08-29T13:30:00+00:00",
                    "league": "Bundesliga",
                    "home_team": "Spvgg Elversberg",
                    "away_team": "Bayer Leverkusen",
                }
            ]
        )

        refreshed, count = refresh_pending_fixture_dates_from_catalog(ledger, fixtures)

        self.assertEqual(count, 1)
        self.assertEqual(refreshed.iloc[0]["date"], "2026-08-29T15:30:00+02:00")
        self.assertEqual(refreshed.iloc[0]["fixture_id"], "sportytrader:123")
        self.assertEqual(refreshed.iloc[0]["kickoff_utc"], "2026-08-29T13:30:00+00:00")

    def test_fixture_id_is_preferred_over_names(self) -> None:
        ledger = pd.DataFrame(
            [
                {
                    "date": "2026-08-29T15:30:00+02:00",
                    "fixture_id": "sportytrader:123",
                    "league": "Bundesliga",
                    "team_name": "Ancien nom",
                    "opponent_name": "Autre ancien nom",
                    "result_status": "pending",
                }
            ]
        )
        fixtures = pd.DataFrame(
            [
                {
                    "official_date": "2026-08-29T15:30:00+02:00",
                    "fixture_id": "sportytrader:123",
                    "kickoff_utc": "2026-08-29T13:30:00Z",
                    "league": "Bundesliga",
                    "home_team": "Nouveau nom",
                    "away_team": "Nouvel adversaire",
                }
            ]
        )

        refreshed, count = refresh_pending_fixture_dates_from_catalog(ledger, fixtures)

        self.assertEqual(count, 1)
        self.assertEqual(refreshed.iloc[0]["kickoff_utc"], "2026-08-29T13:30:00+00:00")

    def test_fixture_catalog_never_rewrites_a_settled_bet(self) -> None:
        ledger = pd.DataFrame(
            [
                {
                    "date": "2026-08-29 07:30:00",
                    "league": "Bundesliga",
                    "team_name": "Spvgg Elversberg",
                    "opponent_name": "Bayer Leverkusen",
                    "result_status": "lost",
                }
            ]
        )
        fixtures = pd.DataFrame(
            [
                {
                    "official_date": pd.Timestamp("2026-08-29 15:30:00"),
                    "league": "Bundesliga",
                    "home_team_norm": "spvgg elversberg",
                    "away_team_norm": "bayer leverkusen",
                }
            ]
        )

        refreshed, count = refresh_pending_fixture_dates_from_catalog(ledger, fixtures)

        self.assertEqual(count, 0)
        self.assertEqual(refreshed.iloc[0]["date"], "2026-08-29 07:30:00")

    def test_pending_prediction_refreshes_only_the_kickoff_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.csv"
            first_bet = pd.DataFrame(
                [
                    {
                        "date": "2026-08-22 10:00:00",
                        "league": "EPL",
                        "team_name": "Ipswich",
                        "opponent_name": "Sunderland",
                        "selected_outcome": "draw",
                        "selected_odds": 3.5,
                        "recommended_bet": True,
                    }
                ]
            )
            corrected_bet = first_bet.copy()
            corrected_bet.loc[0, "date"] = "2026-08-22 16:00:00"
            corrected_bet.loc[0, "selected_odds"] = 3.7

            append_tracking_rows(build_tracking_rows(first_bet, portfolio_name="portfolio"), ledger)
            append_tracking_rows(build_tracking_rows(corrected_bet, portfolio_name="portfolio"), ledger)

            saved = pd.read_csv(ledger)
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved.iloc[0]["date"], "2026-08-22T16:00:00+02:00")
            self.assertEqual(saved.iloc[0]["selected_odds"], 3.5)


if __name__ == "__main__":
    unittest.main()
