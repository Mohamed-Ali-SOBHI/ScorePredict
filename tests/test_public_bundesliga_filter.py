import copy
import unittest
import pandas as pd
from inference.bundesliga_draw_public import qualifies, apply_filter, VERSION
from inference.publication_policy import apply_publication_policy
from inference.upcoming_portfolio_strategy import dedupe_recommended_bets


class PublicBundesligaFilterTests(unittest.TestCase):
    def test_stressed_ev_edge_and_odds_boundaries(self):
        boundary = 1.10 / 4
        self.assertFalse(qualifies(boundary - 1e-9, 4, .20))
        self.assertTrue(qualifies(boundary + 1e-9, 4, .20))
        self.assertFalse(qualifies(.30, 4, .261))
        self.assertTrue(qualifies(.30, 4, .259))
        self.assertTrue(qualifies(.60, 2.2, .20))
        self.assertTrue(qualifies(.28, 4, .20))
        for args in [(.60, 2.19, .20), (.30, 10, .20), (.27, 4, .20),
                     (float('nan'), 4, .20), (.30, float('inf'), .20),
                     (.30, 4, None), (1.1, 4, .2), (.30, 4, -.1)]:
            self.assertFalse(qualifies(*args))

    def test_filter_only_removes_bets_preserving_other_gates_and_deduplication(self):
        row = dict(league='Bundesliga', selected_outcome='draw', strategy_name='draw_low',
                   predicted_probability=.3, selected_odds=4., market_probability=.25,
                   recommended_bet='draw', bet_key='one|draw', expected_value=.2, edge=.05,
                   date='2026-10-26', team_name='Home')
        frame = pd.DataFrame([row, dict(row, strategy_name='draw_high'),
            dict(row, bet_key='two|draw', predicted_probability=.28),
            dict(row, bet_key='three|draw', recommended_bet=''),
            dict(row, league='EPL', selected_outcome='away_win', strategy_name='english',
                 bet_key='four|away_win', recommended_bet='away_win', predicted_probability=.28)])
        original=frame.copy(deep=True);filtered=apply_filter(frame)
        pd.testing.assert_frame_equal(frame, original)
        self.assertEqual(filtered.recommended_bet.tolist(), ['draw','draw','','','away_win'])
        self.assertIn(VERSION, filtered.iloc[0].strategy_name)
        self.assertEqual(filtered.iloc[-1].strategy_name, 'english')
        pd.testing.assert_frame_equal(filtered, apply_filter(filtered))
        self.assertEqual(set(dedupe_recommended_bets(filtered).bet_key), {'one|draw','four|away_win'})
        self.assertTrue(apply_filter(pd.DataFrame()).empty)

    def test_published_tickets_survive_even_when_the_new_filter_rejects_them(self):
        old=dict(id='published', league='Bundesliga', outcome='draw', odds=4.,
                 modelProbability=.28, recordedAt='2026-10-24T09:00:00Z',
                 date='2026-10-25T15:00:00Z', status='lost', profitUnits=-1,
                 strategy='draw_low')
        source=dict(activity=[old],predictions=[]);saved=copy.deepcopy(source)
        result=apply_publication_policy(source)
        self.assertEqual(result['activity'],[old])
        self.assertEqual(result['summary']['liveProfitUnits'],-1)
        self.assertEqual(result['meta']['publicStrategies'][0]['evThreshold'],.10)
        self.assertEqual(result['meta']['publicStrategies'][0]['priceHaircut'],0.)
        self.assertTrue(result['meta']['publicStrategies'][0]['historyIncludesPreviousFilters'])
        self.assertEqual(source,saved)
