import copy
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

import numpy as np
import pandas as pd
import requests

from inference.price_only_inputs import identify_price_candidates, price_frame
from inference.public_additions import ENGLAND_HOME, select_public_bets
from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME
from inference.live_tracking import build_tracking_rows, append_tracking_rows
from production.understat_fallback import availability, merge_snapshot


class UnderstatFallbackTests(unittest.TestCase):
    def test_transport_failure_only_and_automatic_recovery(self):
        bad = Mock(side_effect=requests.exceptions.ConnectionError('DNS failed'))
        self.assertEqual(availability(2026, bad)['mode'], 'price_only')
        good = Mock(return_value=Mock(headers={}, json=lambda: {'dates': [], 'teams': {'1': {}}}))
        self.assertEqual(availability(2026, good)['mode'], 'normal')
        maintenance = Mock(headers={'Content-Type': 'text/html'},
                           text='<title>Understat.com</title><p>We will come back soon</p>')
        self.assertEqual(availability(2026, Mock(return_value=maintenance))['mode'], 'price_only')
        maintenance.json.assert_not_called()
        maintenance.text = '<html>Unexpected content</html>'
        maintenance.json.side_effect = ValueError('not JSON')
        with self.assertRaises(ValueError):
            availability(2026, Mock(return_value=maintenance))
        for error in [requests.exceptions.SSLError('certificate'), ValueError('invalid JSON')]:
            with self.assertRaises(type(error)):
                availability(2026, Mock(side_effect=error))
        response = Mock(status_code=404)
        with self.assertRaises(requests.exceptions.HTTPError):
            availability(2026, Mock(side_effect=requests.exceptions.HTTPError(response=response)))
        response.status_code = 503
        self.assertEqual(availability(2026, Mock(side_effect=requests.exceptions.HTTPError(response=response)))['mode'], 'price_only')

    def identify(self, rows, catalogs=None, now='2026-11-06T10:00:00Z'):
        catalogs = catalogs if catalogs is not None else [dict(league='EPL', fixture_id='sporty:1',
            schedule_source='sportytrader_jsonld_utc', kickoff_utc='2026-11-06T20:00:00Z',
            home_team='Arsenal', away_team='Chelsea')]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.csv'
            with path.open('w', newline='', encoding='utf8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(catalogs[0]))
                writer.writeheader(); writer.writerows(catalogs)
            return identify_price_candidates(rows, path, pd.Timestamp(now))

    def fixture(self, **kw):
        return dict(Div='E0', Date='06/11/2026', Time='20:00', HomeTeam='Arsenal', AwayTeam='Chelsea',
                    B365H='2.3', B365D='3.4', B365A='3.1') | kw

    def test_cross_source_schedule_odds_and_window_guards(self):
        candidates, rejected = self.identify([self.fixture()])
        self.assertEqual(len(candidates), 1); self.assertFalse(rejected)
        for row in [self.fixture(Time='21:00'), self.fixture(B365H='nan'), self.fixture(B365A=''),
                    self.fixture(HomeTeam='Unknown'), self.fixture(Date='01/11/2026')]:
            self.assertFalse(self.identify([row])[0])
        for now in ['2026-11-06T19:56:00Z', '2026-11-04T10:00:00Z']:
            self.assertFalse(self.identify([self.fixture()], now=now)[0])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.identify([self.fixture(), self.fixture()])
        self.assertFalse(self.identify([self.fixture(Div='D1')])[0])

    def test_price_only_input_model_and_full_vector_parity(self):
        # Isolate frozen imports exactly as the production worker does.
        code = '''
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'paper_positive15'))
from run_paper import check_registration
from paper_models import Models
from inference.price_only_inputs import price_frame
import numpy as np,pandas as pd
check_registration(); models=Models(); checked=0
for sample in json.loads(Path('tests/fixtures/public_additions_parity.json').read_text()):
 if sample['model']!='local_price_only':continue
 original=pd.DataFrame([sample['features']])
 prices={o:sample['features']['market_'+c+'_odds_open'] for o,c in [('home','home_win'),('draw','draw'),('away','away_win')]}
 minimal=price_frame(prices)
 expected,_=models.score(original,['local_price_only'])
 actual,inputs=models.score(minimal,['local_price_only'])
 np.testing.assert_array_equal(actual['local_price_only'],expected['local_price_only'])
 np.testing.assert_allclose(actual['local_price_only'][0,sample['class']],sample['probability'],rtol=1e-6,atol=1e-7)
 assert len(inputs['local_price_only'].columns)==12
 assert all(c.startswith('market_') for c in inputs['local_price_only'])
 checked+=1
assert checked>0
print('Exact prediction parity confirmed:',checked)
'''
        env = os.environ.copy(); env['PYTHONPATH'] = os.pathsep.join(str(p) for p in sys.path if p)
        subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1], env=env, check=True, timeout=120)

    def test_published_tickets_are_not_replaced_or_duplicated(self):
        source = dict(fixture_id='sporty:1', kickoff_utc='2026-11-06T20:00:00Z', date='2026-11-06T21:00:00+01:00',
                      league='EPL', team_name='Arsenal', opponent_name='Chelsea', selected_outcome='home_win',
                      selected_odds=2.3, predicted_probability=.6, strategy_name=ENGLAND_HOME,
                      strategy_names=ENGLAND_HOME, recommended_bet='home_win', stake_eur=2.5)
        tracked = build_tracking_rows(pd.DataFrame([source]), portfolio_name=DEFAULT_PORTFOLIO_NAME)
        tracked['prediction_generated_at_utc'] = '2026-11-06T09:00:00+00:00'
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / 'ledger.csv'
            append_tracking_rows(tracked, ledger)
            changed = tracked.copy(); changed['selected_odds'] = 9
            append_tracking_rows(changed, ledger)
            actual = pd.read_csv(ledger)
            self.assertEqual(len(actual), 1); self.assertEqual(actual.selected_odds.iloc[0], 2.3)
        existing = tracked.copy(); existing['selected_outcome'] = 'away_win'; existing['strategy_names'] = 'another'
        self.assertTrue(select_public_bets(pd.DataFrame([source]), existing, DEFAULT_PORTFOLIO_NAME).empty)

    def test_worker_end_to_end_never_requests_understat(self):
        code = '''
import csv,json,runpy,sys,tempfile
from pathlib import Path
from unittest.mock import patch,Mock
import pandas as pd
kickoff=(pd.Timestamp.now(tz='UTC')+pd.Timedelta(hours=6)).floor('min')
uk=kickoff.tz_convert('Europe/London')
body=('Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A\\n'
      f'E0,{uk:%d/%m/%Y},{uk:%H:%M},Arsenal,Chelsea,2.3,3.4,3.1\\n').encode()
def fetch(url,**kwargs):
 assert url=='https://www.football-data.co.uk/fixtures.csv',url
 return Mock(content=body)
with tempfile.TemporaryDirectory() as folder:
 path=Path(folder);catalog=path/'catalog.csv';output=path/'scored.csv'
 pd.DataFrame([dict(league='EPL',fixture_id='sporty:1',schedule_source='sportytrader_jsonld_utc',
   kickoff_utc=kickoff.isoformat(),home_team='Arsenal',away_team='Chelsea')]).to_csv(catalog,index=False)
 sys.argv=['worker','--catalog',str(catalog),'--output',str(output),'--price-only']
 with patch('requests.get',side_effect=fetch) as request:
  runpy.run_path('inference/public_additions_worker.py',run_name='__main__')
  assert request.call_count==1
 result=pd.read_csv(output)
 assert len(result)==1 and result.iloc[0].strategy_name=='public_epl_home_price_2026_10_25'
 audit=json.loads(next(path.glob('capture-*/audit.json')).read_text())
 assert len(audit['forecasts'][0]['features'])==12
 assert audit['forecasts'][0]['history']['sports_required'] is False
'''
        env = os.environ.copy(); env['PYTHONPATH'] = os.pathsep.join(str(p) for p in sys.path if p)
        subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1], env=env, check=True, timeout=120)

    def test_snapshot_keeps_history_and_stale_sporting_timestamp(self):
        ledger = pd.DataFrame([dict(snapshot_key='saved', fixture_id='sporty:old', kickoff_utc='2026-11-01T20:00:00Z',
            date='2026-11-01T21:00:00+01:00', league='EPL', team_name='Arsenal', opponent_name='Chelsea',
            selected_outcome='home_win', strategy_names=ENGLAND_HOME, selected_odds=2.3,
            predicted_probability=.6, prediction_generated_at_utc='2026-11-01T10:00:00Z',
            portfolio_name=DEFAULT_PORTFOLIO_NAME, recommended=True, result_status='won',
            realized_profit_units=1.3, actual_home_score=2, actual_away_score=1, stake_eur=2.5)])
        original = dict(meta=dict(activePortfolio=DEFAULT_PORTFOLIO_NAME, latestPredictionAt='2026-11-01T10:00:00Z'),
                        activity=[], predictions=[], quality={'generatedAt': '2026-11-01T10:00:00Z'})
        saved = copy.deepcopy(original)
        result = merge_snapshot(original, ledger, datetime(2026,11,6,12,tzinfo=timezone.utc))
        self.assertEqual(original, saved)
        self.assertEqual(result['meta']['latestPredictionAt'], saved['meta']['latestPredictionAt'])
        self.assertEqual(result['quality']['generatedAt'], saved['quality']['generatedAt'])
        self.assertEqual(result['summary']['liveProfitUnits'], 1.3)
        self.assertEqual(result['activity'][0]['odds'], 2.3)
        self.assertEqual(result['activity'][0]['status'], 'won')
        self.assertEqual(result['predictions'], [])
        self.assertEqual(result['quality']['overallStatus'], 'partial')


if __name__ == '__main__':
    unittest.main()
