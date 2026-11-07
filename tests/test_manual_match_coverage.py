from datetime import datetime, timezone
import unittest
import pandas as pd

from production.manual_match_coverage import eligible, archived
from train.make_dataset import compute_match_elo, EloConfig


class ManualMatchCoverageTests(unittest.TestCase):
    def event(self, home, away, day, available):
        from inference.espn_results import team_name
        return dict(home=team_name(home), away=team_name(away), kickoff=f'2026-11-{day:02d}T15:00:00+00:00', available=available)

    def test_missing_match_only_blocks_its_dependencies_not_entire_league(self):
        scope = {'events': [self.event('newcastle', 'everton', 2, False), self.event('arsenal', 'chelsea', 3, True)]}
        cutoff = '2026-11-04T15:00:00Z'
        self.assertFalse(eligible(scope, 'Fulham', 'Newcastle United', cutoff)['eligible'])
        self.assertTrue(eligible(scope, 'Arsenal', 'Chelsea', cutoff)['eligible'])

    def test_elo_contamination_propagates_to_later_opponents(self):
        scope = {'events': [self.event('newcastle', 'everton', 2, False),
                            self.event('everton', 'arsenal', 3, True),
                            self.event('arsenal', 'chelsea', 4, True)]}
        result = eligible(scope, 'Chelsea', 'Fulham', '2026-11-05T15:00:00Z')
        self.assertFalse(result['eligible'])
        self.assertEqual(set(result['affectedTeams']), {'newcastle united', 'everton', 'arsenal', 'chelsea'})

    def test_three_day_cutoff_and_result_availability_are_respected(self):
        scope = {'events': [self.event('newcastle', 'everton', 2, False)]}
        self.assertTrue(eligible(scope, 'Newcastle', 'Everton', '2026-11-02T16:59:59Z')['eligible'])
        self.assertFalse(eligible(scope, 'Newcastle', 'Everton', '2026-11-02T17:00:00Z')['eligible'])
        self.assertFalse(eligible(scope, 'Newcastle', 'Everton', '2026-11-02T15:01:00Z', availability_hours=0)['eligible'])

    def test_scoped_dependency_rule_matches_actual_elo_engine(self):
        rows = [dict(match_id='missing', league='EPL', season=2026, date=pd.Timestamp('2026-11-02'),
                     home_team_id='A', away_team_id='B', result='w'),
                dict(match_id='clean', league='EPL', season=2026, date=pd.Timestamp('2026-11-03'),
                     home_team_id='C', away_team_id='D', result='w'),
                dict(match_id='chain', league='EPL', season=2026, date=pd.Timestamp('2026-11-04'),
                     home_team_id='B', away_team_id='C', result='l'),
                dict(match_id='future', league='EPL', season=2026, date=pd.Timestamp('2026-11-05'),
                     home_team_id='C', away_team_id='D', result=None)]
        complete = compute_match_elo(pd.DataFrame(rows), EloConfig()).set_index('match_id')
        incomplete = compute_match_elo(pd.DataFrame(rows[1:]), EloConfig()).set_index('match_id')
        pd.testing.assert_series_equal(complete.loc['clean'], incomplete.loc['clean'])
        self.assertNotEqual(complete.loc['future','team_elo_rating'], incomplete.loc['future','team_elo_rating'])

    def test_both_archives_are_authentic_and_predate_manual_run(self):
        for league, count in [('Bundesliga',72),('EPL',89)]:
            payload=archived(league)
            self.assertEqual(sum(g['isResult'] is True for g in payload['dates']),count)
            self.assertTrue(payload['captured_at'].startswith('2026-11-01'))


if __name__ == '__main__':
    unittest.main()
