"""Synthetic tests never enter the real prospective journal."""
import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
import numpy as np
import pandas as pd
from paper_core import MEMBERS,Journal,allocations,decisions,digest,performance,stamp,utcnow,validate_receipt
ROOT=Path(__file__).resolve().parent

def example():
    now=utcnow();reg={'registered_at_utc':(now-timedelta(minutes=2)).isoformat()}
    p={'original_xgb_ensemble':{'away':.30,'draw':.40,'home':.30}};odds={'away':3.,'draw':4.,'home':2.5}
    choices=decisions('Bundesliga',p,odds)
    receipt={'fixture_id':'test-only:1','registration_sha256':digest(reg),'league':'Bundesliga','kickoff_utc':(now+timedelta(hours=2)).isoformat(),
        'recorded_at_utc':now.isoformat(),'quotes_collected_at_utc':now.isoformat(),'sports_collected_at_utc':now.isoformat(),
        'production_snapshot_completed_at_utc':now.isoformat(),'reference':None,'probabilities':p,'odds':odds,
        'decisions':choices,'portfolios':allocations(None,choices)}
    return reg,receipt,now

class PaperTests(unittest.TestCase):
    def test_late_capture_and_future_input_rejected(self):
        reg,r,now=example();validate_receipt(r,reg['registered_at_utc'],now)
        for field,value in [('kickoff_utc',(now-timedelta(seconds=1)).isoformat()),
            ('quotes_collected_at_utc',(now+timedelta(seconds=1)).isoformat()),
            ('quotes_collected_at_utc',(now-timedelta(hours=1)).isoformat()),
            ('production_snapshot_completed_at_utc',(now-timedelta(hours=25)).isoformat())]:
            bad=copy.deepcopy(r);bad[field]=value
            with self.assertRaises(ValueError):validate_receipt(bad,reg['registered_at_utc'],now)
    def test_changed_decisions_rejected(self):
        reg,r,now=example();r['portfolios']['reference_bundesliga_half']['stake']=1
        with self.assertRaises(ValueError):validate_receipt(r,reg['registered_at_utc'],now)
    def test_baseline_priority_and_conflict_deduplication(self):
        choices=[{'member':m['id'],'selected':True,'outcome':m['outcome'],'odds':4.} for m in MEMBERS if m['league']=='Serie_A']
        a=allocations(None,choices)
        self.assertEqual(a['reference_six_full']['source'],'seriea_draw_poisson')
        self.assertEqual(a['reference_six_half']['stake'],.5)
        reference={'outcome':'away','odds':3.2};b=allocations(reference,choices)
        for name in ['reference_six_full','reference_six_half','reference_bundesliga_half','reference_seriea_draw_poisson']:
            self.assertEqual(b[name],{'source':'reference','outcome':'away','odds':3.2,'stake':1.})
    def test_journal_immutable_idempotent_and_no_backfill(self):
        reg,r,now=example()
        with tempfile.TemporaryDirectory() as tmp:
            j=Journal(Path(tmp)/'test.sqlite',reg)
            self.assertTrue(j.append('forecast',r['fixture_id'],r));self.assertFalse(j.append('forecast',r['fixture_id'],r))
            altered=copy.deepcopy(r);altered['odds']['draw']=4.1
            with self.assertRaises(ValueError):j.append('forecast',r['fixture_id'],altered)
            with self.assertRaises(sqlite3.IntegrityError):j.db.execute("UPDATE events SET payload='{}'")
            j.db.rollback()
            with self.assertRaises(sqlite3.IntegrityError):j.db.execute('DELETE FROM events')
            j.db.rollback()
            late=copy.deepcopy(r);late['fixture_id']='late';late['kickoff_utc']=(now-timedelta(days=1)).isoformat()
            with self.assertRaises(ValueError):j.append('forecast','late',late)
            with self.assertRaises(ValueError):Journal(Path(tmp)/'test.sqlite',{'registered_at_utc':now.isoformat()})
            j.verify();j.db.close()
    def test_settlement_requires_future_elapsed_and_correct_forecast(self):
        reg,r,now=example()
        with tempfile.TemporaryDirectory() as tmp:
            j=Journal(Path(tmp)/'test.sqlite',reg);j.append('forecast',r['fixture_id'],r)
            settledtime=now+timedelta(hours=5)
            s={'forecast_sha256':digest(r),'outcome':'draw','result_seen_at_utc':settledtime.isoformat()}
            with self.assertRaises(ValueError):j.append('settlement',r['fixture_id'],s)
            with patch('paper_core.utcnow',return_value=settledtime):self.assertTrue(j.append('settlement',r['fixture_id'],s))
            metrics={x['portfolio']:x for x in performance(j.records('forecast'),j.records('settlement'))}
            self.assertEqual(metrics['reference']['profit'],0)
            self.assertEqual(metrics['reference_bundesliga_half']['profit'],1.5)
            self.assertEqual(metrics['reference_six_full']['profit'],3)
            j.db.close()
    def test_pending_never_counts_as_profit_or_settled_exposure(self):
        _,r,_=example();m={x['portfolio']:x for x in performance({'a':r},{})}
        self.assertEqual(m['reference_bundesliga_half']['pending_stake'],.5)
        self.assertEqual(m['reference_bundesliga_half']['settled_stake'],0)
        self.assertIsNone(m['reference_bundesliga_half']['roi'])
    def test_model_adapter_matches_archived_frozen_predictions(self):
        from paper_models import Models
        source=ROOT/'test_fixtures/model_parity.csv.gz'
        original=pd.read_csv(source);models=Models()
        for name in ['poisson_sports','logit_sports','outcome_control','original_xgb_ensemble']:
            sample=original[original.model.eq(name)&original.league.eq('Bundesliga')].head(4).copy()
            p,_=models.score(sample,[name])
            np.testing.assert_allclose(p[name],sample[['p_away','p_draw','p_home']],rtol=1e-6,atol=1e-7)
    def test_pending_feature_construction_matches_causal_archive(self):
        from paper_models import Models,frame_for_fixture,FEATURES
        panel=pd.read_csv(ROOT/'test_fixtures/causal_features.csv.gz');raw=pd.read_pickle(ROOT/'frozen/history_through_previous_season.pkl')
        for league in ['Bundesliga','Serie_A']:
            row=panel[panel.league.eq(league)&panel.has_B365_pre].iloc[-1]
            quotes={}
            for book in ['B365','Avg','BW','WH']:
                quotes[book]={o:float(row[f'quote_{book}_pre_{o}']) for o in ['away','draw','home']} if row[f'has_{book}_pre'] else None
            kickoff=pd.Timestamp(row.date).tz_localize('UTC')
            fixture={'league':league,'kickoff_utc':kickoff.isoformat(),'home_id':str(row.team_id),'away_id':str(row.opponent_id),
                     'home_team':row.team_name,'away_team':row.opponent_name}
            f,_=frame_for_fixture(raw,fixture,quotes,kickoff-pd.Timedelta(hours=20))
            columns=list(dict.fromkeys(FEATURES+Models().features))
            np.testing.assert_allclose(f[columns].iloc[0].to_numpy(float),row[columns].to_numpy(float),rtol=1e-8,atol=1e-8,equal_nan=True)
    def test_eligible_fixture_requires_verified_schedule_and_triplet(self):
        from run_paper import identify_candidates
        now=utcnow();ko=now+timedelta(hours=10)
        row={'Div':'D1','Date':ko.strftime('%d/%m/%Y'),'HomeTeam':'Bayern Munich','AwayTeam':'Augsburg','B365H':'1.5','B365D':'4','B365A':'6'}
        source={'fixtures':[row],'Bundesliga':{'dates':[{'id':'123','isResult':False,'datetime':ko.strftime('%Y-%m-%d %H:%M:%S'),
                'h':{'id':'117','title':'Bayern Munich'},'a':{'id':'118','title':'Augsburg'}}]}}
        import csv
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'catalog.csv';fields=['league','schedule_source','fixture_id','kickoff_utc','home_team','away_team']
            with path.open('w',newline='',encoding='utf8') as file:
                w=csv.DictWriter(file,fieldnames=fields);w.writeheader();w.writerow(dict(zip(fields,['Bundesliga','sportytrader_jsonld_utc','sportytrader:test',ko.isoformat(),'Bayern Munich','Augsburg'])))
            eligible,rejected=identify_candidates(source,path)
            self.assertEqual(len(eligible),1);self.assertEqual(eligible[0]['fixture_id'],'understat:123')
            row['B365D']='';eligible,rejected=identify_candidates(source,path)
            self.assertEqual(len(eligible),0);self.assertEqual(rejected[0]['reason'],'required_same_provider_triplet_missing')
    def test_postponed_results_are_quarantined(self):
        from run_paper import settle
        reg,r,now=example();r.update(home_id='1',away_id='2')
        future=now+timedelta(days=2)
        class Fake:
            def records(self,kind):return {'test-only:1':r} if kind=='forecast' else {}
        sources={'Bundesliga':{'dates':[{'id':'1','isResult':True,'datetime':future.strftime('%Y-%m-%d %H:%M:%S'),
                 'h':{'id':'1'},'a':{'id':'2'},'goals':{'h':'0','a':'0'}}]}}
        # Matching canonical prefix, but a moved kickoff must never settle automatically.
        r['fixture_id']='understat:1'
        class FakeJournal:
            def records(self,kind):return {'understat:1':r} if kind=='forecast' else {}
        n,issues=settle(FakeJournal(),sources,{'Bundesliga':{'retrieved_at_utc':(future+timedelta(hours=3)).isoformat()}})
        self.assertEqual(n,0);self.assertEqual(issues[0]['reason'],'schedule_changed_or_timezone_discrepancy_requires_review')

if __name__=='__main__':unittest.main(verbosity=2)
