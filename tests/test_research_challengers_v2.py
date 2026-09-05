from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from train.research_challengers_v2 import (
    apply_betting_policy, choose_candidate, features, fit_betting_policy,
    summarize_bets, temporal_split,
)


def sample_predictions() -> pd.DataFrame:
    count = 120
    return pd.DataFrame({
        "match_id": [f"match-{i}" for i in range(count)],
        "date": pd.date_range("2024-08-01", periods=count),
        "season": 2024,
        "league": "Bundesliga",
        "target": np.arange(count) % 3,
        "p_away": .25, "p_draw": .45, "p_home": .30, "p_binary_draw": .47,
        "market_away_prob_open": .30, "market_draw_prob_open": .25, "market_home_prob_open": .45,
        "market_draw_odds_open": 3.9,
    })


class ResearchChallengerTests(unittest.TestCase):
    def test_calendar_overlap_is_rejected_even_with_distinct_season_numbers(self):
        data = pd.DataFrame({"match_id": ["a", "b", "c"], "season": [2022, 2023, 2024],
                             "date": pd.to_datetime(["2023-09-01", "2023-08-01", "2024-08-01"])})
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            temporal_split(data, 2024)

    def test_split_excludes_future_and_validation_labels_from_training(self):
        data = pd.DataFrame({"match_id": list("abcd"), "season": [2022, 2023, 2024, 2025],
                             "date": pd.to_datetime([f"{y}-08-01" for y in (2022, 2023, 2024, 2025)])})
        train, val, test = temporal_split(data, 2024)
        self.assertEqual(train.match_id.tolist(), ["a"])
        self.assertEqual(val.match_id.tolist(), ["b"])
        self.assertEqual(test.match_id.tolist(), ["c"])

    def test_test_outcomes_do_not_change_selected_bets(self):
        validation = sample_predictions()
        decisions = fit_betting_policy(validation, "legacy")
        self.assertTrue(decisions)
        test = sample_predictions()
        ids_before = apply_betting_policy(test, decisions).match_id.tolist()
        test["target"] = 2
        ids_after = apply_betting_policy(test, decisions).match_id.tolist()
        self.assertEqual(ids_before, ids_after)

    def test_confirmation_profit_cannot_choose_the_challenger(self):
        earlier = sample_predictions().assign(selected_odds=3.9, target=1)
        earlier = pd.concat([earlier.assign(season=season, match_id=lambda x: x.match_id + str(season))
                             for season in (2020, 2021, 2022)], ignore_index=True)
        later = sample_predictions().assign(selected_odds=100, target=1)
        candidates = {"a": earlier, "b": earlier.assign(target=2)}
        before, _ = choose_candidate(candidates)
        candidates["b"] = pd.concat([candidates["b"], later], ignore_index=True)
        after, _ = choose_candidate(candidates)
        self.assertEqual(before, "a")
        self.assertEqual(before, after)

    def test_features_exclude_scores_targets_and_closing_odds(self):
        rows = sample_predictions().assign(actual_home_score=7, team_goals=7, market_draw_odds_close=2)
        selected = features(rows, enriched=True)
        for forbidden in ("actual_home_score", "team_goals", "target", "market_draw_odds_close", "season"):
            self.assertNotIn(forbidden, selected.columns)

    def test_zero_bets_is_missing_return_and_duplicate_bets_are_rejected(self):
        self.assertIsNone(summarize_bets(pd.DataFrame())["roi"])
        bets = sample_predictions().assign(selected_odds=3.9)
        with self.assertRaisesRegex(ValueError, "counted twice"):
            summarize_bets(pd.concat([bets, bets], ignore_index=True))


if __name__ == "__main__":
    unittest.main()
