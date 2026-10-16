import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from production.dashboard import _kickoff, DashboardService
from production.explorer import build_explorer


class ExplorerTests(unittest.TestCase):
    def test_explicit_utc_wins_over_legacy_time(self):
        row = {'date':'2026-09-12 13:30:00','kickoff_utc':'2026-09-12T13:30:00Z'}
        self.assertEqual(_kickoff(row), '2026-09-12T15:30:00+02:00')
        self.assertEqual(_kickoff({'kickoff_utc':'2026-12-12T13:30:00Z'}), '2026-12-12T14:30:00+01:00')

    def test_stats_exclude_same_match_and_future(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            folder=root/'Data'/'EPL'
            folder.mkdir(parents=True)
            (folder/'2026 A.csv').write_text('match_id,date,team_name,result,team_goals\n1,2026-09-01,A,w,2\n2,2026-09-12,A,w,99\n3,2026-09-13,A,w,99\n')
            row={'date':'2026-09-12 15:00:00','league':'EPL','team_name':'A','opponent_name':'B','pred_home_win':.4,'pred_draw':.3,'pred_away_win':.3,'recommended_bet':False}
            result=build_explorer(root,[row,row],datetime(2026,9,12,8,tzinfo=timezone.utc))
            self.assertEqual(len(result['matches']),1)
            self.assertEqual(result['matches'][0]['teams'][0]['averages']['goals'],2)
            self.assertIsNone(result['matches'][0]['teams'][1]['averages']['goals'])
            self.assertNotIn('stakeEur',result['matches'][0])

    def test_verified_name_alias_recovers_history_without_crossing_leagues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for league, goals in [('Ligue_1', 2), ('EPL', 99)]:
                folder = root/'Data'/league
                folder.mkdir(parents=True)
                (folder/'2026 Le Mans.csv').write_text(
                    'match_id,date,team_name,result,team_goals\n'
                    f'1,2026-09-01,Le Mans,w,{goals}\n'
                    '2,2026-09-12,Le Mans,w,99\n', encoding='utf8')
            row = {'date':'2026-09-12 15:00:00', 'league':'Ligue_1',
                   'team_name':'Le Mans FC', 'opponent_name':'Toulouse',
                   'pred_home_win':.4, 'pred_draw':.3, 'pred_away_win':.3}
            match = build_explorer(root, [row], datetime(2026,9,12,8,tzinfo=timezone.utc))['matches'][0]
            self.assertEqual(match['homeTeam'], 'Le Mans FC')
            self.assertEqual(match['teams'][0]['played'], 1)
            self.assertEqual(match['teams'][0]['form'], ['w'])
            self.assertEqual(match['teams'][0]['averages']['goals'], 2)
            self.assertIsNone(match['teams'][1]['averages']['goals'])

    def test_invalid_probabilities_not_invented(self):
        with tempfile.TemporaryDirectory() as directory:
            row={'date':'2026-09-12 15:00:00','league':'EPL','team_name':'A'}
            self.assertEqual(build_explorer(Path(directory),[row],datetime(2026,9,12,8,tzinfo=timezone.utc))['matches'],[])
