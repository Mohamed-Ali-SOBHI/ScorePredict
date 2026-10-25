import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from inference import bundesliga_observation as private
from inference.bundesliga_draw_public import apply_filter as public_filter
from inference.bundesliga_draw_recalibrated import apply_filter as private_filter
from inference.publication_policy import apply_publication_policy
from inference.supabase_prediction_store import remote_records

class BundesligaObservationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.folder=Path(tmp.name)
        for name,value in [('STATE',self.folder),('LEDGER',self.folder/'ledger.csv'),('STATUS',self.folder/'status.json'),('REPORT',self.folder/'report.json')]:
            p=patch.object(private,name,value);p.start();self.addCleanup(p.stop)
        self.now=pd.Timestamp('2026-10-26T10:00:00Z')

    def forecasts(self,verified=True):
        r=dict(fixture_id='id1',match_id='id1',date='2026-10-26T16:00:00+01:00',kickoff_utc='2026-10-26T15:00:00Z',league='Bundesliga',
          team_name='Home',opponent_name='Away',strategy_name='bundesliga_draw_original',selected_outcome='draw',recommended_bet='draw',
          predicted_probability=.32,raw_model_probability=.32,multiclass_draw_probability=.35,binary_draw_probability=.32,
          selected_odds=4.,market_away_win_odds_open=2.,market_home_win_odds_open=3.,market_probability=3/13,edge=.32-3/13,
          expected_value=.28,quote_observed_at_utc='2026-10-26T09:55:00Z',features_available_at_utc='2026-10-25T00:00:00Z',
          bookmaker='B365',price_type='executable',bet_key='id1|draw')
        if not verified:
            for c in ['quote_observed_at_utc','features_available_at_utc','bookmaker','price_type']:r.pop(c)
        return pd.DataFrame([r])

    def test_public_old_gate_and_private_new_gate_are_distinct(self):
        f=self.forecasts();f['predicted_probability']=.28
        self.assertEqual(public_filter(f).iloc[0].recommended_bet,'draw')
        self.assertEqual(private_filter(f).iloc[0].recommended_bet,'')

    def test_registration_preserves_audited_model_hashes_and_limits(self):
        p=private.policy();self.assertEqual(p['max_loss_from_start_units'],10);self.assertEqual(p['max_new_bets'],100)
        self.assertEqual(p['filter']['price_haircut'],.02)

    def test_no_retroactive_enrollment_and_no_mutation(self):
        f=self.forecasts();original=f.copy(deep=True)
        private.record_forecasts(f,now='2026-10-25T10:00:00Z')
        self.assertEqual(private.export_report(now=self.now)['observations'],0)
        private.record_forecasts(pd.concat([f,f]),now=self.now)
        private.record_forecasts(f.assign(selected_odds=8),now=self.now+pd.Timedelta(minutes=5))
        report=private.export_report(now=self.now+pd.Timedelta(minutes=6))
        self.assertEqual(report['observations'],1);self.assertEqual(report['monitor']['pending'],1)
        self.assertEqual(report['decision_receipts'][0]['decision']['odds_draw'],4)
        self.assertEqual(report['ledger'][0]['portfolio_name'],private.PORTFOLIO)
        pd.testing.assert_frame_equal(f,original)
        stored=remote_records(private.rows())[0]
        self.assertEqual(json.loads(stored['probability_note'])['decision']['selected'],1)

    def test_unverified_source_is_observed_but_not_confirmation(self):
        private.record_forecasts(self.forecasts(False),now=self.now)
        report=private.export_report(now=self.now)
        self.assertEqual(report['observations'],1);self.assertEqual(report['unverified_observations'],1)
        self.assertEqual(report['monitor']['bets'],0)
        self.assertEqual(report['decision_receipts'][0]['decision']['selected'],0)

    def test_private_rows_cannot_leak_and_both_public_filter_histories_survive(self):
        old=dict(id='old',league='Bundesliga',outcome='draw',strategy='old',status='lost',profitUnits=-1)
        new=dict(old,id='new',strategy='old__filter_bundesliga_draw_recalibrated_2026_10_25')
        secret=dict(old,id='private',strategy=private.PORTFOLIO)
        source=dict(activity=[old,new,secret],predictions=[secret]);saved=copy.deepcopy(source)
        out=apply_publication_policy(source)
        self.assertEqual([r['id'] for r in out['activity']],['old','new']);self.assertEqual(out['predictions'],[])
        self.assertEqual(out['summary']['liveProfitUnits'],-2);self.assertEqual(source,saved)

    def test_pending_stakes_cannot_exceed_loss_budget(self):
        frames=[]
        for i in range(12):frames.append(self.forecasts().assign(fixture_id=f'id{i}',match_id=f'id{i}',team_name=f'Home{i}',bet_key=f'id{i}|draw'))
        private.record_forecasts(pd.concat(frames),now=self.now)
        report=private.export_report(now=self.now)
        self.assertEqual(report['observations'],12);self.assertEqual(report['monitor']['pending'],10)
        self.assertEqual(report['monitor']['status'],'suspendre_exposition')

    def test_official_settlement_survives_reruns_and_keeps_original_receipt(self):
        private.record_forecasts(self.forecasts(),now=self.now)
        initial=private.export_report(now=self.now)['decision_receipts'][0]['decision']
        result=pd.DataFrame([dict(league='Bundesliga',home_team_norm='home',away_team_norm='away',
            official_date=pd.Timestamp('2026-10-26T16:00:00'),status='FT',home_score=1,away_score=1,
            result_source='test_official')])
        with patch('inference.result_monitor.collect_results_for_due_rows',return_value=(result,{})):
            private.settle(now='2026-10-26T18:00:00Z')
        report=private.export_report(now='2026-10-26T18:00:00Z')
        self.assertEqual(report['monitor']['gain'],3)
        self.assertEqual(report['monitor']['pending'],0)
        self.assertEqual(report['decision_receipts'][0]['decision'],initial)
        self.assertEqual(report['diagnostics']['hypothetical_gain_at_displayed_prices'],3)
        with patch('inference.result_monitor.collect_results_for_due_rows',return_value=(result.assign(home_score=2),{})):
            private.settle(now='2026-10-27T18:00:00Z')
        again=private.export_report(now='2026-10-27T18:00:00Z')
        self.assertEqual(again['monitor']['gain'],3)
        self.assertEqual(again['decision_receipts'][0]['settled_at_utc'],'2026-10-26T18:00:00+00:00')
        with patch('inference.supabase_prediction_store.push',return_value=1) as push:
            private.persist()
            push.assert_called_once_with(private.LEDGER,private.STATUS,portfolio_name=private.PORTFOLIO)

if __name__=='__main__':unittest.main()
