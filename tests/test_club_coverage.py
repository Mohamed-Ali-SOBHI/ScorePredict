import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from data_pipeline.audit_club_coverage import audit_features, audit_league, audit_upcoming
from data_pipeline.scrapper import extract_stats_from_data, update_stats_with_opponents, get_league_data


class ClubCoverageTests(unittest.TestCase):
    def setUp(self):
        self.date = "2026-10-01 18:45:00"
        home = dict(date=self.date, h_a="h", xG=1.5, xGA=.5, scored=2, missed=0,
                    npxG=1.5, npxGA=.5, ppda={"att": 100, "def": 10},
                    ppda_allowed={"att": 200, "def": 20}, deep=4, deep_allowed=2,
                    xpts=2.4, result="w")
        away = dict(date=self.date, h_a="a", xG=.5, xGA=1.5, scored=0, missed=2,
                    npxG=.5, npxGA=1.5, ppda={"att": 200, "def": 20},
                    ppda_allowed={"att": 100, "def": 10}, deep=2, deep_allowed=4,
                    xpts=.3, result="l")
        self.payload = {"teams": {"1": dict(id="1", title="Le Mans", history=[home]),
                                  "2": dict(id="2", title="Toulouse", history=[away])},
                        "dates": [dict(id="11", isResult=True, datetime=self.date,
                                       h=dict(id="1", title="Le Mans"),
                                       a=dict(id="2", title="Toulouse"),
                                       goals=dict(h="2", a="0"), xG=dict(h="1.5", a=".5"))]}
        data = {"Ligue_1 2026": self.payload["teams"]}
        stats = update_stats_with_opponents(extract_stats_from_data(data), data)
        self.rows = [r for group in stats.values() for r in group]
        self.registry = [dict(team_id="1", team_name="Le Mans FC"), dict(team_id="2", team_name="Toulouse")]

    def audit(self):
        return audit_league(self.payload, self.registry, self.rows, league="Ligue_1", season=2026, expected_count=2)

    def test_complete_alias_history_and_missing_optional_market_are_valid(self):
        report = self.audit()
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["clubs"][0]["optional_missing"]["team_shots"], 1)

    def test_placeholder_cannot_hide_played_club(self):
        self.registry[0]["team_id"] = "new-placeholder"
        self.rows = self.rows[1:]
        self.assertTrue(any("Played club absent" in e for e in self.audit()["errors"]))

    def test_equal_row_count_cannot_hide_missing_match(self):
        self.rows[0]["date"] = "2026-09-01 18:45:00"
        self.assertTrue(any("Saved coverage differs" in e for e in self.audit()["errors"]))

    def test_source_missing_history_is_detected_against_fixtures(self):
        self.payload["teams"]["1"]["history"] = []
        self.assertTrue(any("source history" in e for e in self.audit()["errors"]))

    def test_missing_nonfinite_or_changed_sporting_values_fail(self):
        baseline = copy.deepcopy(self.rows)
        for value in (None, "nan", float("inf"), -.1, 42):
            with self.subTest(value=value):
                self.rows = copy.deepcopy(baseline)
                self.rows[0]["team_xG"] = value
                self.assertTrue(any("team_xG" in e for e in self.audit()["errors"]))

    def test_missing_nested_source_stat_fails(self):
        del self.payload["teams"]["1"]["history"][0]["ppda"]["att"]
        self.assertTrue(any("team_ppda_att" in e for e in self.audit()["errors"]))

    def test_wrong_opponent_and_duplicate_rows_fail(self):
        self.rows[0]["opponent_id"] = "999"
        self.rows.append(copy.deepcopy(self.rows[0]))
        errors = self.audit()["errors"]
        self.assertTrue(any("Duplicate saved" in e for e in errors))
        self.assertTrue(any("incorrect opponent" in e for e in errors))

    def test_zero_matches_before_season_is_valid(self):
        self.payload["dates"][0]["isResult"] = False
        for team in self.payload["teams"].values():
            team["history"] = []
        self.rows = []
        self.assertEqual(self.audit()["errors"], [])

    def test_warmup_allowed_but_missing_features_after_playing_fail(self):
        row = dict(match_id="example", matches_played_in_season_before=0,
                   opponent_matches_played_in_season_before=1)
        for side in ("team", "opponent"):
            for metric in ("xG", "xG_against", "deep", "deep_against", "ppda_att", "ppda_def"):
                row[f"{side}_{metric}_last_1"] = float("nan") if side == "team" else 1.
        self.assertEqual(audit_features(pd.DataFrame([row])), [])
        row["matches_played_in_season_before"] = 1
        self.assertEqual(len(audit_features(pd.DataFrame([row]))), 6)

    def test_exact_source_snapshot_survives_registry_filtering(self):
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: self.payload)
        with tempfile.TemporaryDirectory() as directory:
            with patch("data_pipeline.scrapper.requests.get", return_value=response), patch(
                "data_pipeline.scrapper._current_registry_titles", return_value={}
            ):
                get_league_data("Ligue_1", 2026, source_snapshot_dir=directory)
            saved = json.loads((Path(directory)/"Ligue_1-2026.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["teams"], self.payload["teams"])
            self.assertEqual(saved["dates"], self.payload["dates"])
            self.assertTrue(saved["captured_at"])

    def test_live_input_checks_use_only_prior_observations(self):
        raw = pd.DataFrame([
            dict(league="Ligue_1", season=2026, team_id="1", date=pd.Timestamp("2026-10-01")),
            dict(league="Ligue_1", season=2026, team_id="2", date=pd.Timestamp("2026-10-01")),
            dict(league="Ligue_1", season=2026, team_id="1", date=pd.Timestamp("2026-10-20")),
        ])
        row = dict(match_id="future", league="Ligue_1", season=2026,
                   team_id="1", opponent_id="2", team_name="Le Mans", opponent_name="Toulouse",
                   date=pd.Timestamp("2026-10-16"), matches_played_in_season_before=1,
                   opponent_matches_played_in_season_before=1)
        for side in ("team", "opponent"):
            for metric in ("xG", "xG_against", "deep", "deep_against", "ppda_att", "ppda_def"):
                row[f"{side}_{metric}_last_1"] = 1.
        bundle = SimpleNamespace(feature_cols=["team_xG_last_1"], secondary_feature_cols=None)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"audit.json"
            report = audit_upcoming(raw, pd.DataFrame([row]), {"model": bundle}, output)
            self.assertEqual(report["status"], "passed")
            row["matches_played_in_season_before"] = 0
            with self.assertRaisesRegex(ValueError, "history count"):
                audit_upcoming(raw, pd.DataFrame([row]), {"model": bundle}, output)
            self.assertEqual(json.loads(output.read_text())["status"], "failed")


if __name__ == "__main__":
    unittest.main()
