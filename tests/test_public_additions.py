import copy,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from inference.public_additions import BUNDESLIGA,ENGLAND_HOME,ACTIVATED_AT,qualifies,select_public_bets,score_public_additions
from inference.publication_policy import apply_publication_policy
from inference.english_away_public import STRATEGY as AWAY


class PublicAdditionsTests(unittest.TestCase):
    def row(self,strategy=BUNDESLIGA,fixture='game',outcome='draw',**kw):
        return dict(fixture_id=fixture,strategy_name=strategy,league='Bundesliga' if outcome=='draw' else 'EPL',
            date='2026-10-27T19:00:00Z',team_name='Home',opponent_name='Away',selected_outcome=outcome,
            recommended_bet=outcome,selected_odds=4.,predicted_probability=.4,expected_value=.5,edge=.1,**kw)

    def test_existing_strategies_win_over_higher_ev_additions_and_opposing_choices(self):
        rows=[self.row(),self.row('original'),self.row(ENGLAND_HOME,'english','home_win'),self.row(AWAY,'english','away_win')]
        selected=select_public_bets(pd.DataFrame(rows))
        self.assertEqual(set(selected.strategy_names),{'original',AWAY})
        self.assertEqual(len(selected),2)
        rows[1]['recommended_bet']='';rows[3]['recommended_bet']=''
        selected=select_public_bets(pd.DataFrame(rows))
        self.assertEqual(set(selected.strategy_names),{BUNDESLIGA,ENGLAND_HOME})

    def test_published_match_cannot_switch_outcome_or_strategy_on_later_run(self):
        held=self.row(ENGLAND_HOME,'english','home_win',portfolio_name='public',recommended=True)
        held['strategy_names']=ENGLAND_HOME
        ledger=pd.DataFrame([held]);saved=ledger.copy(deep=True)
        self.assertTrue(select_public_bets(pd.DataFrame([self.row(AWAY,'english','away_win')]),ledger,'public').empty)
        self.assertEqual(len(select_public_bets(pd.DataFrame([self.row(ENGLAND_HOME,'english','home_win')]),ledger,'public')),1)
        ledger['fixture_id']=''
        self.assertTrue(select_public_bets(pd.DataFrame([self.row(AWAY,'new-id','away_win')]),ledger,'public').empty)
        self.assertEqual(saved.iloc[0].selected_odds,4.)

    def test_activation_private_history_and_strict_filter_boundaries(self):
        boundary=1.02/(4*.98)
        self.assertFalse(qualifies(boundary-1e-9,4))
        self.assertTrue(qualifies(boundary+1e-9,4))
        for p,o in [(1,1.19),(.9,10.01),(float('nan'),4),(.5,float('inf')),(-1,4)]:self.assertFalse(qualifies(p,o))
        self.assertTrue(qualifies(.9,1.2));self.assertTrue(qualifies(.2,10))
        for identity,league,outcome in [(BUNDESLIGA,'Bundesliga','draw'),(ENGLAND_HOME,'EPL','home_win')]:
            ticket=dict(strategy=identity,league=league,outcome=outcome,recordedAt=ACTIVATED_AT,date='2026-10-27T19:00:00Z',odds=4,modelProbability=.4,status='pending')
            source=dict(activity=[ticket],predictions=[ticket]);saved=copy.deepcopy(source)
            result=apply_publication_policy(source)
            self.assertEqual(len(result['activity']),1);self.assertEqual(len(result['meta']['publicStrategies']),4)
            self.assertEqual(source,saved);self.assertEqual(result,apply_publication_policy(result))
            for changes in [dict(recordedAt='2026-10-24T12:00:00Z'),dict(recordedAt='2026-10-26T12:00:00'),dict(odds=11),dict(portfolio_name='observation_private'),dict(outcome='away_win')]:
                row=dict(ticket,**changes)
                self.assertEqual(apply_publication_policy(dict(activity=[row],predictions=[row]))['activity'],[])

    def test_worker_abstentions_and_canonical_mapping(self):
        def fake(command,**kw):
            pd.DataFrame([dict(fixture_id='game',kickoff_utc='2026-10-27T19:00:00Z',strategy_name=ENGLAND_HOME,
                selected_outcome='home_win',recommended_bet='')]).to_csv(command[-1],index=False)
        with tempfile.TemporaryDirectory() as folder,patch('subprocess.run',side_effect=fake):
            scored=score_public_additions('catalog.csv',pd.DataFrame([dict(fixture_id='game',match_id='canonical')]),folder)
        self.assertEqual(scored.iloc[0].recommended_bet,'')
        self.assertEqual(scored.iloc[0].bet_key,'canonical|home_win')
        self.assertEqual(str(scored.iloc[0].date),'2026-10-27 20:00:00')

    def test_frozen_worker_models_reproduce_simulation_without_retraining(self):
        code='''
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'paper_positive15'))
from run_paper import check_registration
from paper_models import Models
import numpy as np,pandas as pd
check_registration()
model=Models()
for sample in json.loads(Path('tests/fixtures/public_additions_parity.json').read_text()):
 frame=pd.DataFrame([sample['features']])
 for col in frame:
  if col!='league':frame[col]=pd.to_numeric(frame[col],errors='raise').astype(float)
 p,_=model.score(frame,[sample['model']])
 np.testing.assert_allclose(p[sample['model']][0,sample['class']],sample['probability'],rtol=1e-6,atol=1e-7)
 frame['target']=-999
 for col in frame:
  if '_close' in col:frame[col]=float('nan')
 poisoned,_=model.score(frame,[sample['model']]);np.testing.assert_array_equal(p[sample['model']],poisoned[sample['model']])
'''
        env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join(str(p) for p in sys.path if p)
        subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[1],check=True,env=env,timeout=120)


if __name__=='__main__':unittest.main()
