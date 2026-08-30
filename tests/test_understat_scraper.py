from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from data_pipeline.market_data import MarketDataUnavailableError
from data_pipeline.scrapper import normalize_understat_teams, save_data
from train.make_dataset import load_team_match_rows


class UnderstatTeamNormalizationTests(unittest.TestCase):
    def test_recovers_missing_title_from_fixture_metadata(self) -> None:
        payload = {
            "teams": {
                "164": {"id": "164", "title": "Marseille", "history": []},
                "225": {"history": [{"date": "2026-08-21 19:00:00"}]},
            },
            "dates": [
                {
                    "h": {"id": "164", "title": "Marseille"},
                    "a": {"id": "225", "title": "Strasbourg"},
                }
            ],
        }

        teams = normalize_understat_teams(payload)

        self.assertEqual(teams["225"]["id"], "225")
        self.assertEqual(teams["225"]["title"], "Strasbourg")
        self.assertEqual(len(teams["225"]["history"]), 1)

    def test_preserves_registered_clubs_before_they_have_history(self) -> None:
        payload = {
            "teams": [{"id": "164", "title": "Marseille", "history": []}],
            "dates": [],
        }

        teams = normalize_understat_teams(payload, fallback_titles={"225": "Strasbourg"})

        self.assertEqual(set(teams), {"164", "225"})
        self.assertEqual(teams["225"], {"id": "225", "title": "Strasbourg", "history": []})

    def test_does_not_duplicate_a_club_after_understat_assigns_a_real_id(self) -> None:
        payload = {
            "teams": [{"id": "294", "title": "Coventry", "history": []}],
            "dates": [],
        }

        teams = normalize_understat_teams(
            payload,
            fallback_titles={"new-47498f991a7b": "Coventry City"},
            expected_team_count=1,
        )

        self.assertEqual(set(teams), {"294"})

    def test_complete_registry_filters_stale_source_clubs(self) -> None:
        payload = {
            "teams": [
                {"id": "164", "title": "Marseille", "history": [{"date": "2026-08-21"}]},
                {"id": "225", "title": "Strasbourg", "history": []},
                {"id": "old-1", "title": "Nantes", "history": []},
                {"id": "old-2", "title": "Metz", "history": []},
            ],
            "dates": [],
        }

        teams = normalize_understat_teams(
            payload,
            fallback_titles={"164": "Marseille", "225": "Strasbourg"},
            expected_team_count=2,
        )

        self.assertEqual(set(teams), {"164", "225"})
        self.assertEqual(len(teams["164"]["history"]), 1)

    def test_incomplete_registry_does_not_hide_new_source_clubs(self) -> None:
        payload = {
            "teams": [
                {"id": "164", "title": "Marseille", "history": []},
                {"id": "225", "title": "Strasbourg", "history": []},
            ],
            "dates": [],
        }

        teams = normalize_understat_teams(
            payload,
            fallback_titles={"164": "Marseille"},
            expected_team_count=2,
        )

        self.assertEqual(set(teams), {"164", "225"})

    def test_rejects_an_unknown_name_instead_of_publishing_a_fake_club(self) -> None:
        payload = {"teams": {"999": {"history": []}}, "dates": []}

        with self.assertRaisesRegex(ValueError, "teams, dates, or the current registry"):
            normalize_understat_teams(payload)

    def test_keeps_fresh_understat_rows_when_market_file_is_unavailable(self) -> None:
        stats = {
            "Bundesliga 2026 Bayern Munich": [
                {
                    "match_id": "Bundesliga 2026_1_2_2026-08-29 13:30:00",
                    "date": "2026-08-29 13:30:00",
                    "is_home": True,
                    "team_id": "1",
                    "team_name": "Bayern Munich",
                    "result": "w",
                    "opponent_id": "2",
                    "opponent_name": "Hamburger SV",
                    "team_xG": 2.4,
                    "team_goals": 3,
                    "team_ppda_att": 8.1,
                    "team_ppda_def": 21.0,
                    "team_deep": 13,
                    "team_xpts": 2.5,
                    "team_npxG": 2.4,
                    "opponent_xG": 0.7,
                    "opponent_goals": 1,
                    "opponent_ppda_att": 12.0,
                    "opponent_ppda_def": 15.0,
                    "opponent_deep": 4,
                    "opponent_npxG": 0.7,
                }
            ]
        }

        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                with patch(
                    "data_pipeline.scrapper.enrich_team_rows_with_market_data",
                    side_effect=MarketDataUnavailableError("market source unavailable"),
                ):
                    save_data(stats)

                output = os.path.join(temp_dir, "Data", "Bundesliga", "2026 Bayern Munich.csv")
                self.assertTrue(os.path.exists(output))
                saved = pd.read_csv(output)
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved.loc[0, "team_xG"], 2.4)
                self.assertEqual(saved.loc[0, "team_ppda_att"], 8.1)
                self.assertTrue(pd.isna(saved.loc[0, "team_win_odds_open"]))
                self.assertTrue(pd.isna(saved.loc[0, "draw_odds_open"]))
                self.assertTrue(pd.isna(saved.loc[0, "opponent_win_odds_open"]))

                loaded = load_team_match_rows(os.path.join(temp_dir, "Data"))
                self.assertEqual(len(loaded), 1)
                self.assertEqual(loaded.loc[0, "season"], 2026)
                self.assertEqual(loaded.loc[0, "team_xG"], 2.4)
            finally:
                os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
