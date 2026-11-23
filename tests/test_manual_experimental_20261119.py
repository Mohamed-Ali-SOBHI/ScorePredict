import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
import pandas as pd

from inference.live_tracking import build_tracking_rows
from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME
from production.manual_experimental_20261119 import RECEIPT, candidate_rows, exclude_held
from production.understat_fallback import EXPERIMENT_NOTICE, merge_snapshot

NOW = datetime(2026, 11, 19, 19, 0, tzinfo=timezone.utc)


class ExperimentalWeekend(unittest.TestCase):
    def setUp(self):
        self.receipt = json.loads(RECEIPT.read_text(encoding='utf8'))
        self.boards = {
            'Bundesliga': pd.DataFrame([
                dict(home_team_norm='eintracht frankfurt', away_team_norm='hoffenheim', official_date='2026-11-21 15:30:00'),
                dict(home_team_norm='elversberg', away_team_norm='freiburg', official_date='2026-11-21 15:30:00')]),
            'EPL': pd.DataFrame([
                dict(home_team_norm='chelsea', away_team_norm='leeds', official_date='2026-11-21 16:00:00'),
                dict(home_team_norm='tottenham', away_team_norm='ipswich', official_date='2026-11-21 16:00:00')])}

    def test_receipt_and_independent_fixture_validation(self):
        bets = candidate_rows(self.receipt, self.boards, NOW)
        self.assertEqual(len(bets), 4)
        self.assertEqual(bets.selected_odds.tolist(), [4., 3.75, 3.9, 6.])
        with self.assertRaises(ValueError):
            candidate_rows(self.receipt, self.boards, NOW + timedelta(hours=4))
        bad = copy.deepcopy(self.receipt); bad['picks'][0]['odds'][1] = 2
        with self.assertRaises(ValueError):
            candidate_rows(bad, self.boards, NOW)
        board = copy.deepcopy(self.boards); board['EPL'].loc[0, 'official_date'] = '2026-11-21 17:00:00'
        with self.assertRaises(ValueError):
            candidate_rows(self.receipt, board, NOW)

    def test_no_duplicate_or_opposing_pick_and_early_display(self):
        bets = candidate_rows(self.receipt, self.boards, NOW)
        existing = build_tracking_rows(bets.iloc[[0]], portfolio_name=DEFAULT_PORTFOLIO_NAME)
        existing.loc[0, 'selected_outcome'] = 'home_win'
        self.assertEqual(len(exclude_held(bets, existing)), 3)
        bets['stake_eur'] = 2.5
        ledger = build_tracking_rows(bets, portfolio_name=DEFAULT_PORTFOLIO_NAME)
        snapshot = merge_snapshot({'meta': {'activePortfolio': DEFAULT_PORTFOLIO_NAME},
                                   'activity': [], 'predictions': []}, ledger, NOW)
        self.assertEqual(len(snapshot['predictions']), 2)
        self.assertTrue(all(p['earlyPublished'] for p in snapshot['predictions']))
        self.assertEqual(snapshot['meta']['serviceNotice'], EXPERIMENT_NOTICE)
        later = merge_snapshot(snapshot, ledger, NOW + timedelta(minutes=1))
        self.assertEqual(len(later['predictions']), 2)
        self.assertEqual(later['meta']['serviceNotice'], EXPERIMENT_NOTICE)


if __name__ == '__main__':
    unittest.main()
