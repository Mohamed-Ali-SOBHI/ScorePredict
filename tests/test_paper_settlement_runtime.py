import copy
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from production import paper_settlement_runtime as runtime


class SettlementTimezoneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.folder = self.state / 'captures' / 'prematch'
        self.folder.mkdir(parents=True)
        self.first = {'id': '31998', 'isResult': False, 'datetime': '2026-10-18 15:15:00',
                      'h': {'id': '179'}, 'a': {'id': '171'}, 'goals': {'h': None, 'a': None}}
        self.content = json.dumps({'dates': [self.first]}).encode()
        (self.folder / 'Ligue_1.json.gz').write_bytes(gzip.compress(self.content))
        self.forecast = {'fixture_id': 'understat:31998', 'league': 'Ligue_1',
            'kickoff_utc': '2026-10-18T13:15:00Z', 'recorded_at_utc': '2026-10-17T13:49:50Z',
            'home_id': '179', 'away_id': '171', 'capture_directory': 'captures/prematch',
            'schedule_source': 'sportytrader_jsonld_utc',
            'source_snapshot_sha256': {'Ligue_1': hashlib.sha256(self.content).hexdigest()}}
        self.game = dict(self.first, isResult=True, goals={'h': '1', 'a': '0'})
        self.sources = {'Ligue_1': {'dates': [self.game]}}

    def normalize(self, forecast=None, sources=None):
        return runtime.normalize_settlement_sources(self.state,
            {'understat:31998': forecast or self.forecast}, sources or self.sources)

    def test_exact_lorient_regression_without_modifying_sources_or_forecast(self):
        original = copy.deepcopy((self.sources, self.forecast))
        normalized, audit = self.normalize()
        self.assertEqual(normalized['Ligue_1']['dates'][0]['datetime'], '2026-10-18 13:15:00')
        self.assertEqual(audit['corrections'][0]['timezone'], 'Europe/Paris')
        self.assertTrue(audit['corrections'][0]['within_original_30min_tolerance'])
        self.assertEqual(audit['unresolved'], [])
        self.assertEqual((self.sources, self.forecast), original)

    def test_real_postponement_still_exceeds_original_tolerance(self):
        for time in ['2026-10-18 17:15:00', '2026-10-18 13:15:00', '2026-10-19 15:15:00']:
            with self.subTest(time=time):
                sources={'Ligue_1': {'dates': [dict(self.game, datetime=time)]}}
                _, audit = self.normalize(sources=sources)
                self.assertFalse(audit['corrections'][0]['within_original_30min_tolerance'])

    def test_winter_dst_and_already_utc_dates(self):
        cases=[('2026-12-06 15:15:00','2026-12-06T14:15:00Z','Ligue_1'),
               ('2026-10-18 13:15:00','2026-10-18T13:15:00Z','Ligue_1'),
               ('2026-10-18 16:30:00','2026-10-18T15:30:00Z','EPL')]
        for wall, kickoff, league in cases:
            converted,_=runtime.resolve(wall,wall,kickoff,league)
            self.assertEqual(converted,runtime.utc(kickoff))
        self.assertEqual(runtime.resolve('2026-10-18 15:15:00','2026-10-18T15:15:00+02:00',
            '2026-10-18T13:15:00Z','Ligue_1')[0],runtime.utc('2026-10-18T13:15:00Z'))

    def test_invalid_anchor_or_ambiguous_dst_is_not_guessed(self):
        for first, current, kickoff in [
            ('2026-10-18 19:15:00','2026-10-18 19:15:00','2026-10-18T13:15:00Z'),
            ('2026-03-29 02:30:00','2026-03-29 02:30:00','2026-03-29T01:30:00Z'),
            ('2026-10-24 15:15:00','2026-10-25 02:30:00','2026-10-24T13:15:00Z')]:
            with self.subTest(first=first), self.assertRaises(ValueError):
                runtime.resolve(first,current,kickoff,'Ligue_1')

    def test_tampered_missing_and_wrong_event_sources_fail_closed(self):
        for changes in [{'source_snapshot_sha256': {'Ligue_1': 'bad'}}, {'home_id': 'wrong'},
                        {'capture_directory': '../outside'}, {'schedule_source': 'unverified'},
                        {'recorded_at_utc': '2026-10-19T13:00:00Z'}]:
            with self.subTest(changes=changes):
                _, audit = self.normalize(forecast=dict(self.forecast, **changes))
                self.assertEqual(len(audit['unresolved']),1)
                def original(journal,sources,metadata):
                    self.assertEqual(journal.records('forecast'),{})
                    return 0,[]
                class Journal:
                    def records(_self,kind):return {'understat:31998': self.forecast}
                count,issues=runtime.settle_normalized(original,Journal(),self.sources,{},audit)
                self.assertEqual(count,0)
                self.assertEqual(issues[0]['reason'],'settlement_timezone_unresolved')

    def test_manifest_keeps_both_original_registrations_and_code_frozen(self):
        for experiment in ['paper_simulation','paper_positive15']:
            root=runtime.ROOT / experiment
            registration=json.loads((root/'registration.json').read_text(encoding='utf8'))
            runtime.verify_amendment(experiment,registration)
            for name, sha in registration['frozen_sha256'].items():
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),sha,name)

    def test_live_entrypoint_refuses_local_execution(self):
        with patch.dict('os.environ',{'GITHUB_ACTIONS':'false'}), patch('sys.argv',['runtime','--experiment','paper_simulation']):
            with self.assertRaisesRegex(ValueError,'GitHub Actions only'):
                runtime.main()

    def test_both_unchanged_collectors_settle_once_and_still_quarantine_moves(self):
        # Separate processes prevent the two frozen paper_core modules colliding.
        code='''
import copy,importlib,json,sys
from pathlib import Path
from production.paper_settlement_runtime import normalize_settlement_sources,settle_normalized
experiment,state,forecast_json,sources_json=sys.argv[1:]
sys.path.insert(0,str(Path.cwd()/experiment))
collector=importlib.import_module('run_paper');collector.check_registration()
f=json.loads(forecast_json);sources=json.loads(sources_json)
class Journal:
 def __init__(self):self.results={}
 def records(self,kind):return {f['fixture_id']:f} if kind=='forecast' else self.results
 def append(self,kind,identity,payload):self.results[identity]=payload;return True
j=Journal();metadata={'Ligue_1':{'retrieved_at_utc':'2026-10-18T20:00:00Z','url':'archived-test','sha256':'current-source'}}
n,a=normalize_settlement_sources(Path(state),j.records('forecast'),sources)
assert settle_normalized(collector.settle,j,n,metadata,a)==(1,[])
assert j.results[f['fixture_id']]['outcome']=='home'
before=copy.deepcopy(j.results)
assert settle_normalized(collector.settle,j,n,metadata,a)==(0,[])
assert before==j.results
for time in ['2026-10-18 17:15:00','2026-10-18 13:15:00','2026-10-19 15:15:00']:
 sources['Ligue_1']['dates'][0]['datetime']=time
 n,a=normalize_settlement_sources(Path(state),j.records('forecast'),sources)
 count,issues=settle_normalized(collector.settle,j,n,metadata,a)
 assert count==0 and len(issues)==1,(time,count,issues)
assert before==j.results
sources=json.loads(sources_json)
sources['Ligue_1']['dates'][0]['h']['id']='different-team'
n,a=normalize_settlement_sources(Path(state),j.records('forecast'),sources)
count,issues=settle_normalized(collector.settle,j,n,metadata,a)
assert count==0 and issues[0]['reason']=='changed_teams_requires_review'
sources=json.loads(sources_json)
sources['Ligue_1']['dates'][0]['goals']={'h':'0','a':'1'}
n,a=normalize_settlement_sources(Path(state),j.records('forecast'),sources)
count,issues=settle_normalized(collector.settle,j,n,metadata,a)
assert count==0 and issues[0]['reason']=='source_result_revision_requires_review'
assert before==j.results
'''
        for experiment in ['paper_simulation','paper_positive15']:
            subprocess.run([sys.executable,'-c',code,experiment,str(self.state),json.dumps(self.forecast),json.dumps(self.sources)],
                cwd=runtime.ROOT,check=True,timeout=30)


if __name__ == '__main__':unittest.main()
