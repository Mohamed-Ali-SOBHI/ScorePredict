from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from data_pipeline.market_data import (
    MarketDataUnavailableError,
    build_match_market_table,
    normalize_team_name,
    parse_market_csv_text,
)


class MarketDataTests(unittest.TestCase):
    @staticmethod
    def _current_season() -> int:
        today = pd.Timestamp.now()
        return today.year if today.month >= 7 else today.year - 1

    def test_current_la_liga_market_aliases(self) -> None:
        expected_names = {
            "Atl. Madrid": "atletico madrid",
            "Dep. A Coruna": "deportivo la coruna",
            "Santander": "racing santander",
        }

        for source_name, expected_name in expected_names.items():
            with self.subTest(source_name=source_name):
                self.assertEqual(normalize_team_name(source_name), expected_name)

    def test_rejects_an_html_multiple_choices_page(self) -> None:
        html = "<!DOCTYPE HTML><html><title>300 Multiple Choices</title></html>"

        with self.assertRaisesRegex(MarketDataUnavailableError, "unavailable"):
            parse_market_csv_text(html, "https://example.test/E0.csv")

    def test_accepts_a_minimal_valid_market_csv(self) -> None:
        csv_text = "Date,HomeTeam,AwayTeam,HS,AS,B365H,B365D,B365A\n21/08/2026,Arsenal,Coventry,10,5,1.2,7.9,20.0\n"

        frame = parse_market_csv_text(csv_text, "https://example.test/E0.csv")

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["HomeTeam"], "Arsenal")

    @staticmethod
    def _team_rows(match_date: str) -> pd.DataFrame:
        season = MarketDataTests._current_season()
        return pd.DataFrame(
            [
                {
                    "match_id": f"La_liga {season}_delayed",
                    "date": match_date,
                    "league": "La_liga",
                    "season": season,
                    "team_name": "Real Sociedad",
                    "opponent_name": "Real Betis",
                    "is_home": True,
                }
            ]
        )

    @staticmethod
    def _market_rows() -> pd.DataFrame:
        season = MarketDataTests._current_season()
        return pd.DataFrame(
            [
                {
                    "league": "La_liga",
                    "season": season,
                    "market_match_date": pd.Timestamp(f"{season}-08-20"),
                    "home_team_norm": "rayo vallecano",
                    "away_team_norm": "alaves",
                    "home_shots": 10,
                    "away_shots": 8,
                    "home_win_odds_open": 2.0,
                    "draw_odds_open": 3.2,
                    "away_win_odds_open": 4.0,
                }
            ]
        )

    def test_defers_a_match_newer_than_the_latest_market_row(self) -> None:
        season = self._current_season()
        with patch("data_pipeline.market_data.load_market_data", return_value=self._market_rows()):
            with self.assertRaisesRegex(MarketDataUnavailableError, "newer match"):
                build_match_market_table(self._team_rows(f"{season}-08-21"))

    def test_keeps_past_market_mismatches_strict(self) -> None:
        season = self._current_season()
        with patch("data_pipeline.market_data.load_market_data", return_value=self._market_rows()):
            with self.assertRaisesRegex(ValueError, "Failed to match market data"):
                build_match_market_table(self._team_rows(f"{season}-08-19"))


if __name__ == "__main__":
    unittest.main()
