import unittest
import numpy as np
import pandas as pd

from train.research_outside_box_v3 import (
    MEMBERS, checked_goals, goal_probabilities, meta_features, replace_draw,
)
from tests.test_research_challengers_v2 import sample_predictions


class OutsideBoxTests(unittest.TestCase):
    def test_goal_probabilities_are_symmetric_and_normalized(self):
        p = goal_probabilities(np.array([1., 3., .05]), np.array([1., .5, .05]))
        np.testing.assert_allclose(p.sum(axis=1), 1)
        self.assertAlmostEqual(p[0, 0], p[0, 2])
        self.assertGreater(p[1, 2], p[1, 0])
        self.assertGreater(p[2, 1], .9)

    def test_swapping_teams_swaps_home_and_away(self):
        p = goal_probabilities(np.array([.7, 8]), np.array([2., 7.]))
        q = goal_probabilities(np.array([2., 7.]), np.array([.7, 8]))
        np.testing.assert_allclose(p[:, ::-1], q, atol=1e-12)

    def test_goal_labels_must_match_result_and_are_unique(self):
        data = pd.DataFrame({"match_id": ["a", "b"], "target": [2, 1]})
        raw = pd.DataFrame({"match_id": ["a", "b"], "team_goals": [2, 0], "opponent_goals": [0, 0]})
        self.assertEqual(len(checked_goals(raw, data)), 2)
        with self.assertRaisesRegex(ValueError, "disagree"):
            checked_goals(raw.assign(team_goals=3), data)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            checked_goals(pd.concat([raw, raw.assign(team_goals=4)]), data)
        with self.assertRaisesRegex(ValueError, "Missing"):
            checked_goals(raw.iloc[:1], data)

    def test_meta_features_do_not_depend_on_final_result(self):
        frames = {name: sample_predictions() for name in MEMBERS}
        before = meta_features(frames)
        for frame in frames.values():
            frame["target"] = 2
            frame["team_goals"] = 9
            frame["market_draw_odds_close"] = 1.1
        pd.testing.assert_frame_equal(before, meta_features(frames))

    def test_replaced_draw_is_bounded_and_preserves_other_odds_ratio(self):
        frame = sample_predictions().iloc[:3]
        updated = replace_draw(frame, np.array([-1., .6, 2.]))
        np.testing.assert_allclose(updated[["p_away", "p_draw", "p_home"]].sum(axis=1), 1)
        np.testing.assert_allclose(updated.p_away / updated.p_home, frame.p_away / frame.p_home)
        self.assertTrue(updated.p_draw.between(0, 1, inclusive="neither").all())
        pd.testing.assert_series_equal(frame.target, updated.target)


if __name__ == "__main__":
    unittest.main()
