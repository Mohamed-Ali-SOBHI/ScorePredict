import copy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import pandas as pd
from inference.english_away_public import STRATEGY, ACTIVATED_AT, qualifies, fixed_unit_stakes, score_public_english
from inference.publication_policy import apply_publication_policy


class PublicEnglishTests(unittest.TestCase):
    def ticket(self):
        return dict(league='EPL', outcome='away_win', strategy=STRATEGY,
            recordedAt=ACTIVATED_AT, date=(datetime.now(timezone.utc)+timedelta(hours=4)).isoformat(),
            odds=3, modelProbability=.4, status='pending', recommended=True)

    def test_strict_price_and_stressed_ev_boundaries(self):
        self.assertTrue(qualifies(.7,2))
        self.assertTrue(qualifies(.3,6))
        for p, odds in [(.9,1.99),(.9,6.01),(.3,3),(-1,3),(1.1,3),(float('nan'),3),(.8,float('inf'))]:
            self.assertFalse(qualifies(p,odds))
        boundary = 1.1 / (.98 * 4)
        self.assertFalse(qualifies(boundary - 1e-10,4))
        self.assertTrue(qualifies(boundary + 1e-10,4))

    def test_new_strategy_is_public_in_current_picks_and_history(self):
        source = dict(predictions=[self.ticket()], activity=[self.ticket()])
        saved = copy.deepcopy(source)
        result = apply_publication_policy(source)
        self.assertEqual(len(result['predictions']),1)
        self.assertEqual(len(result['activity']),1)
        self.assertEqual(result['predictions'][0]['stakeUnits'],1)
        self.assertEqual(result['meta']['publicLeagues'],['Bundesliga','EPL'])
        self.assertEqual(source,saved)
        self.assertEqual(result,apply_publication_policy(result))

    def test_private_draws_wrong_filters_and_prepublication_bets_stay_private(self):
        for changes in [dict(outcome='draw'),dict(strategy='epl_away_logit'),dict(odds=8),
                        dict(modelProbability=.2), dict(recordedAt='2026-10-18T14:00:00Z'),
                        dict(recordedAt=''), dict(recordedAt='2026-10-18T16:00:00')]:
            row = dict(self.ticket(),**changes)
            result = apply_publication_policy(dict(predictions=[row],activity=[row]))
            self.assertEqual(result['predictions'],[])
            self.assertEqual(result['activity'],[])

    def test_one_unit_does_not_shrink_when_many_fixtures_qualify(self):
        bets = pd.DataFrame({'selected_odds':[3.0]*20})
        fixed = fixed_unit_stakes(bets,2.5)
        self.assertEqual(set(fixed.stake_eur),{2.5})
        self.assertEqual(set(fixed.max_total_exposure_eur),{50.0})

    def test_csv_abstention_remains_an_abstention_and_uses_production_identity(self):
        import tempfile
        def fake_run(command, **kwargs):
            pd.DataFrame([dict(fixture_id='sporty:123',kickoff_utc='2026-10-19T19:00:00Z',
                league='EPL',recommended_bet='',selected_odds=3,selected_outcome='away_win')]).to_csv(command[-1],index=False)
        fixtures=pd.DataFrame([dict(fixture_id='sporty:123')])
        future=pd.DataFrame([dict(fixture_id='sporty:123',match_id='canonical-id')])
        with tempfile.TemporaryDirectory() as folder, patch('subprocess.run',side_effect=fake_run):
            scored=score_public_english('fixtures.csv',fixtures,future,folder)
        self.assertEqual(scored.iloc[0].recommended_bet,'')
        self.assertEqual(scored.iloc[0].bet_key,'canonical-id|away_win')
        self.assertEqual(str(scored.iloc[0].date),'2026-10-19 21:00:00')

    def test_frozen_logit_and_causal_features_match_archive_in_isolated_process(self):
        root=Path(__file__).resolve().parents[1]
        code='''
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()/'paper_simulation'))
from run_paper import check_registration
check_registration()
from paper_models import Models, frame_for_fixture, FEATURES
import numpy as np
import pandas as pd
model=Models()
sample=pd.read_json('tests/fixtures/english_logit_parity.json')
assert len(sample)>0
p,_=model.score(sample,['logit_sports'])
np.testing.assert_allclose(p['logit_sports'],sample[['p_away','p_draw','p_home']],rtol=1e-6,atol=1e-7)
panel=pd.read_csv('paper_simulation/test_fixtures/causal_features.csv.gz')
row=panel[panel.league.eq('Bundesliga') & panel.has_B365_pre].iloc[-1]
quotes={b: {o:float(row[f'quote_{b}_pre_{o}']) for o in ['away','draw','home']} if row[f'has_{b}_pre'] else None for b in ['B365','Avg','BW','WH']}
ko=pd.Timestamp(row.date).tz_localize('UTC')
fixture=dict(league=row.league,kickoff_utc=ko.isoformat(),home_id=str(row.team_id),away_id=str(row.opponent_id),home_team=row.team_name,away_team=row.opponent_name)
raw=pd.read_pickle('paper_simulation/frozen/history_through_previous_season.pkl')
frame,_=frame_for_fixture(raw,fixture,quotes,ko-pd.Timedelta(hours=20))
np.testing.assert_allclose(frame[FEATURES].iloc[0].to_numpy(float),row[FEATURES].to_numpy(float),rtol=1e-8,atol=1e-8,equal_nan=True)
'''
        import os
        env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join(str(p) for p in sys.path if p)
        subprocess.run([sys.executable,'-c',code],cwd=root,check=True,env=env,timeout=120)


if __name__ == '__main__':unittest.main()
