import unittest

import pandas as pd

from train.research_all_outcomes_v2 import apply_filter, summary


class AllOutcomeResearchTests(unittest.TestCase):
    def sample(self):
        return pd.DataFrame({
            "match_id": ["away", "draw", "home"], "season": 2025,
            "date": pd.date_range("2025-08-01", periods=3), "target": [0, 1, 2],
            "p_away": [.6, .2, .2], "p_draw": [.2, .6, .2], "p_home": [.2, .2, .6],
            "market_away_prob_open": .3, "market_draw_prob_open": .25, "market_home_prob_open": .45,
            "market_away_win_odds_open": 2.2, "market_draw_odds_open": 3.8, "market_home_win_odds_open": 2.2,
        })

    def test_accounting_handles_wins_on_all_three_outcomes(self):
        bets = apply_filter(self.sample(), {"ev": .05, "edge": 0})
        self.assertEqual(bets.selected_class.tolist(), [0, 1, 2])
        self.assertAlmostEqual(summary(bets)["profit_units"], 5.2)
        self.assertEqual(summary(bets)["hit_rate"], 1)
        bets.loc[0, "target"] = 2
        self.assertAlmostEqual(summary(bets)["profit_units"], 3.0)

    def test_each_fixture_has_one_choice_independent_of_result(self):
        frame = self.sample()
        first = apply_filter(frame, {"ev": .05, "edge": 0})
        second = apply_filter(frame.assign(target=0), {"ev": .05, "edge": 0})
        self.assertTrue(first.match_id.is_unique)
        self.assertEqual(first.selected_class.tolist(), second.selected_class.tolist())

    def test_rejected_validation_produces_no_bets(self):
        self.assertTrue(apply_filter(self.sample(), None).empty)


if __name__ == "__main__":
    unittest.main()
