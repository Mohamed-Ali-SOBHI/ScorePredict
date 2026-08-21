from __future__ import annotations

import unittest

import pandas as pd

from data_pipeline.build_team_registry_from_fixtures import build_records


class TeamRegistryFromFixturesTests(unittest.TestCase):
    def test_keeps_current_season_clubs_missing_from_partial_fixture_window(self) -> None:
        fixtures = pd.DataFrame(
            [{"league": "EPL", "home_team": "Arsenal", "away_team": "Chelsea"}]
        )
        historical = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-08-01"),
                    "league": "EPL",
                    "season": 2026,
                    "team_id": "83",
                    "team_name": "Arsenal",
                },
                {
                    "date": pd.Timestamp("2026-08-01"),
                    "league": "EPL",
                    "season": 2026,
                    "team_id": "80",
                    "team_name": "Chelsea",
                },
            ]
        )
        current_registry = [
            {
                "league": "EPL",
                "season": 2026,
                "team_id": "72",
                "team_name": "Everton",
            },
            {
                "league": "EPL",
                "season": 2025,
                "team_id": "old",
                "team_name": "Relegated FC",
            },
        ]

        records = build_records(fixtures, historical, 2026, current_registry)

        self.assertEqual(
            {str(row["team_name"]) for row in records},
            {"Arsenal", "Chelsea", "Everton"},
        )


if __name__ == "__main__":
    unittest.main()
