import copy
import json
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from paper_core import MEMBERS,Journal,allocations,decisions,digest,performance,utcnow,validate_receipt

ROOT=Path(__file__).resolve().parent


def example():
    now=utcnow();reg={'registered_at_utc':(now-timedelta(minutes=2)).isoformat()}
    p={m['model']:{'away':.3,'draw':.4,'home':.3} for m in MEMBERS if m['league']=='Bundesliga'}
    odds={'away':3.,'draw':4.,'home':2.5};choices=decisions('Bundesliga',p,odds)
    reference={'outcome':'draw','odds':4.,'generated_at_utc':now.isoformat(),'source':'frozen_Bundesliga_anchor'}
    r={'fixture_id':'test-only:1','registration_sha256':digest(reg),'league':'Bundesliga','kickoff_utc':(now+timedelta(hours=2)).isoformat(),
       'recorded_at_utc':now.isoformat(),'quotes_collected_at_utc':now.isoformat(),'sports_collected_at_utc':now.isoformat(),
       'production_snapshot_completed_at_utc':now.isoformat(),'reference':reference,'probabilities':p,'odds':odds,
       'decisions':choices,'portfolios':allocations(reference,choices)}
    return reg,r,now


class Positive15Tests(unittest.TestCase):
    def test_exact_fifteen_and_original_order(self):
        provenance=json.loads((ROOT/'selection_provenance.json').read_text(encoding='utf8'))
        self.assertEqual(len(MEMBERS),16)
        self.assertEqual([m['id'] for m in MEMBERS[1:]],[c['strategy'] for c in provenance['positive_contributions']])

    def test_duplicates_and_conflicting_outcomes_use_one_unit(self):
        choices=[{'member':m['id'],'selected':True,'outcome':m['outcome'],'odds':4.} for m in MEMBERS if m['league']=='EPL']
        union=allocations(None,choices)['bundesliga_plus15']
        self.assertEqual(union['source'],'local_sport_only|EPL|draw|0.10|all')
        self.assertEqual(union['stake'],1)
        base={'outcome':'draw','odds':3.2}
        union=allocations(base,choices)['bundesliga_plus15']
        self.assertEqual(union,{'source':'reference','outcome':'draw','odds':3.2,'stake':1.})

    def test_profiles_and_strict_ev_boundary(self):
        p={m['model']:{'away':.3,'draw':.4,'home':.3} for m in MEMBERS if m['league']=='Serie_A'}
        odds={'away':4.,'draw':4.,'home':4.}
        context={'q_home':.3,'q_away':.3,'xg_gap_abs':.5,'xg_total':3.}
        choices=decisions('Serie_A',p,odds,context)
        self.assertTrue(all(c['selected'] for c in choices))
        bad=context|{'q_home':.7,'xg_total':3.01}
        choices=decisions('Serie_A',p,odds,bad)
        self.assertFalse(next(c for c in choices if 'low_goal_parity' in c['member'])['selected'])
        self.assertFalse(next(c for c in choices if 'balanced_market' in c['member'])['selected'])
        with self.assertRaises(ValueError):decisions('Serie_A',p,odds)
        p={m['model']:{'away':.25,'draw':.25,'home':.5} for m in MEMBERS if m['league']=='EPL'}
        odds={'away':2.,'draw':2.,'home':(1.02-1e-12)/(.5*.98)}
        choices=decisions('EPL',p,odds)
        self.assertFalse(next(c for c in choices if '|home|' in c['member'])['selected'])

    def test_no_late_backfill_no_replacement_and_no_double_insert(self):
        reg,r,now=example();validate_receipt(r,reg['registered_at_utc'],now)
        for field,value in [('kickoff_utc',(now-timedelta(seconds=1)).isoformat()),('quotes_collected_at_utc',(now+timedelta(seconds=1)).isoformat())]:
            bad=copy.deepcopy(r);bad[field]=value
            with self.assertRaises(ValueError):validate_receipt(bad,reg['registered_at_utc'],now)
        with tempfile.TemporaryDirectory() as tmp:
            j=Journal(Path(tmp)/'journal.sqlite3',reg)
            self.assertTrue(j.append('forecast',r['fixture_id'],r))
            self.assertFalse(j.append('forecast',r['fixture_id'],r))
            bad=copy.deepcopy(r);bad['portfolios']['bundesliga_plus15']['stake']=2
            with self.assertRaises(ValueError):j.append('forecast',r['fixture_id'],bad)
            with self.assertRaises(sqlite3.IntegrityError):j.db.execute('DELETE FROM events')
            j.db.rollback();j.verify();j.db.close()

    def test_pending_excluded_and_settlement_one_profit(self):
        reg,r,now=example()
        rows={x['portfolio']:x for x in performance({'a':r},{})}
        self.assertEqual(rows['bundesliga_plus15']['pending_stake'],1)
        self.assertEqual(rows['bundesliga_plus15']['profit'],0)
        self.assertIsNone(rows['bundesliga_plus15']['roi'])
        with tempfile.TemporaryDirectory() as tmp:
            j=Journal(Path(tmp)/'journal.sqlite3',reg);j.append('forecast',r['fixture_id'],r)
            later=now+timedelta(hours=5)
            settlement={'forecast_sha256':digest(r),'outcome':'draw','result_seen_at_utc':later.isoformat()}
            with self.assertRaises(ValueError):j.append('settlement',r['fixture_id'],settlement)
            with patch('paper_core.utcnow',return_value=later):j.append('settlement',r['fixture_id'],settlement)
            rows={x['portfolio']:x for x in performance(j.records('forecast'),j.records('settlement'))}
            self.assertEqual(rows['bundesliga_plus15']['profit'],3)
            self.assertEqual(rows['bundesliga_plus15']['additional_profit'],0)
            self.assertEqual(rows['bundesliga_plus15']['settled_bets'],1)
            j.db.close()

    def test_all_frozen_model_routes_reproduce_report(self):
        from paper_models import Models
        panel=pd.read_csv(ROOT/'test_fixtures/parity.csv.gz');models=Models()
        for (league,method),g in panel.groupby(['league','model']):
            p,_=models.score(g,[method])
            np.testing.assert_allclose(p[method],g[['p_away','p_draw','p_home']],atol=1e-7,rtol=0)
            poisoned=g.copy()
            for c in poisoned:
                if c in ['target','result','raw_target','raw_home_goals','raw_away_goals'] or '_close' in c:poisoned[c]=np.nan
            again,_=models.score(poisoned,[method])
            np.testing.assert_array_equal(p[method],again[method])

    def test_causal_live_feature_builder(self):
        from paper_models import six,frame_for_fixture
        raw=pd.read_pickle(ROOT.parent/'paper_simulation/frozen/history_through_previous_season.pkl')
        panel=pd.read_csv(ROOT/'test_fixtures/causal.csv.gz')
        for row in panel.itertuples(index=False):
            quote={book:({o:getattr(row,f'quote_{book}_pre_{o}') for o in ['away','draw','home']} if getattr(row,f'has_{book}_pre') else None) for book in ['B365','Avg','BW','WH']}
            kickoff=pd.Timestamp(row.date).tz_localize('UTC')
            fixture={'league':row.league,'kickoff_utc':kickoff.isoformat(),'home_id':str(row.team_id),'away_id':str(row.opponent_id),'home_team':row.team_name,'away_team':row.opponent_name}
            built,_=frame_for_fixture(raw,fixture,quote,kickoff-pd.Timedelta(hours=20))
            cols=six.Models().features
            np.testing.assert_allclose(built[cols].iloc[0].to_numpy(float),[getattr(row,c) for c in cols],equal_nan=True,atol=1e-8,rtol=1e-8)
            before=raw[raw.date+pd.Timedelta(hours=2)<=kickoff.tz_localize(None)-pd.Timedelta(hours=72)]
            repeated,_=frame_for_fixture(before,fixture,quote,kickoff-pd.Timedelta(hours=20))
            extra=[c for c in built if c.startswith('new_sport_')]
            np.testing.assert_allclose(built[extra].iloc[0].to_numpy(float),[getattr(row,c) for c in extra],equal_nan=True,atol=1e-12,rtol=0)
            np.testing.assert_allclose(built[extra],repeated[extra],equal_nan=True,atol=1e-12,rtol=0)


if __name__=='__main__':unittest.main(verbosity=2)
