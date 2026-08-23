from __future__ import annotations

import unittest

from data_pipeline.scrapper import normalize_understat_teams


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


if __name__ == "__main__":
    unittest.main()
