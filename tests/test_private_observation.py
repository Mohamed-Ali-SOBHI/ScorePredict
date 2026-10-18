from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from inference import private_observation as private
from inference.publication_policy import PRIVATE_PORTFOLIO


class PrivateObservationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.state=Path(temp.name)
        for name,value in [('STATE',self.state),('LEDGER',self.state/'ledger.csv'),
                           ('STATUS',self.state/'status.json'),('REPORT',self.state/'report.json')]:
            p=patch.object(private,name,value);p.start();self.addCleanup(p.stop)

    def forecasts(self):
        now=datetime.now(timezone.utc)+timedelta(hours=3)
        rows=[]
        for league,name in [('Bundesliga','bundesliga_draw_4_00_10_00_nonfavorite_4'),
            ('Serie_A','serie_a_draw_4_00_10_00_nonfavorite_2'),('EPL','epl_draw_2_00_10_00_nonfavorite_3')]:
            rows.append({'league':league,'strategy_name':name,'match_id':league+'-test','bet_key':league+'|draw',
                'date':now.isoformat(),'kickoff_utc':now.isoformat(),'fixture_id':league+'-id',
                'team_name':league+' home','opponent_name':'Away','recommended_bet':'draw',
                'selected_outcome':'draw','selected_odds':4.,'predicted_probability':.4,'expected_value':.6,'edge':.15})
        return pd.DataFrame(rows)

    def test_private_namespace_deduplicates_and_preserves_original_forecast_and_result(self):
        first=self.forecasts();private.record_forecasts(first)
        ledger=pd.read_csv(private.LEDGER)
        self.assertEqual(set(ledger.league),{'Serie_A','EPL'})
        self.assertEqual(set(ledger.portfolio_name),{PRIVATE_PORTFOLIO})
        self.assertTrue(ledger.stake_eur.eq(0).all())
        ledger.loc[ledger.league.eq('Serie_A'),'result_status']='won'
        ledger.to_csv(private.LEDGER,index=False)
        second=first.copy();second['selected_odds']=9.;private.record_forecasts(second)
        saved=pd.read_csv(private.LEDGER)
        self.assertEqual(len(saved),2)
        self.assertTrue(saved.selected_odds.eq(4).all())
        self.assertEqual(saved.loc[saved.league.eq('Serie_A'),'result_status'].iloc[0],'won')
        private.export_report();report=json.loads(private.REPORT.read_text(encoding='utf8'))
        serie=next(s for s in report['strategies'] if s['code']=='I01')['metrics']
        self.assertEqual(serie['settled'],1);self.assertEqual(serie['profit'],3.)
        english=next(s for s in report['strategies'] if s['code']=='E01')['metrics']
        self.assertEqual(english['pending'],1);self.assertIsNone(english['roi'])
        self.assertNotIn('Bundesliga',{r['league'] for r in report['tickets']})

    def test_empty_inference_does_not_crash_or_invent_returns(self):
        private.record_forecasts(pd.DataFrame())
        private.export_report();report=json.loads(private.REPORT.read_text(encoding='utf8'))
        self.assertEqual(report['status'],'ready')
        self.assertEqual(report['tickets'],[])
        self.assertTrue(all(s['metrics']['roi'] is None for s in report['strategies']))


if __name__=='__main__':unittest.main()
