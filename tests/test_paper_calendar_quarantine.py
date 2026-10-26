import copy,gzip,hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from production import paper_settlement_runtime_v2 as runtime


class CalendarQuarantineTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.state=Path(temp.name)
        folder=self.state/'captures'/'prematch';folder.mkdir(parents=True)
        self.initial={'id':'32010','isResult':False,'datetime':'2026-10-24 15:15:00',
                      'h':{'id':'174'},'a':{'id':'172'},'goals':{'h':None,'a':None}}
        content=json.dumps({'dates':[self.initial]}).encode()
        (folder/'Ligue_1.json.gz').write_bytes(gzip.compress(content))
        self.forecast={'fixture_id':'understat:32010','league':'Ligue_1','home_id':'174','away_id':'172',
            'home_team':'Toulouse','away_team':'Troyes','kickoff_utc':'2026-10-25T16:15:00+00:00',
            'recorded_at_utc':'2026-10-24T19:02:08.304003+00:00','capture_directory':'captures/prematch',
            'schedule_source':'sportytrader_jsonld_utc','source_snapshot_sha256':{'Ligue_1':hashlib.sha256(content).hexdigest()},
            'reference':None,'decisions':[{'selected':False}],'portfolios':{'reference':None,'candidate':None}}
        self.sources={'Ligue_1':{'dates':[dict(self.initial,isResult=True,goals={'h':'0','a':'0'})]}}

    def test_toulouse_abstention_remains_unsettled_but_is_nonblocking(self):
        before=copy.deepcopy((self.forecast,self.sources))
        normalized,audit=runtime.normalize_settlement_sources(self.state,{'understat:32010':self.forecast},self.sources)
        self.assertEqual(len(audit['unresolved']),1)
        self.assertEqual(len(audit['nonblocking_abstentions']),1)
        self.assertEqual(audit['nonblocking_abstentions'][0]['committed_bets'],0)
        def original(journal,sources,metadata):
            self.assertEqual(journal.records('forecast'),{})
            return 0,[]
        f=self.forecast
        class Journal:
            def records(self,kind):return {f['fixture_id']:f} if kind=='forecast' else {}
            def append(self,*args):raise AssertionError('No result may be invented')
        self.assertEqual(runtime.settle_normalized(original,Journal(),normalized,{},audit),(0,[]))
        self.assertEqual((self.forecast,self.sources),before)

    def test_stakes_selections_reference_or_missing_fields_remain_blocking(self):
        variants=[dict(portfolios={'reference':None,'candidate':{'stake':1}}),dict(decisions=[{'selected':True}]),
                  dict(reference={'outcome':'draw','stake':1}),dict(portfolios={}),dict(portfolios=None),
                  dict(decisions=[]),dict(decisions=[{}]),dict(decisions=[{'selected':0}])]
        for changes in variants:
            with self.subTest(changes=changes):
                f=dict(self.forecast,**changes)
                _,audit=runtime.normalize_settlement_sources(self.state,{f['fixture_id']:f},self.sources)
                self.assertEqual(audit['nonblocking_abstentions'],[])
                self.assertEqual(len(audit['unresolved']),1)
        missing=dict(self.forecast);missing.pop('reference')
        self.assertFalse(runtime.confirmed_abstention(missing))

    def test_bad_archive_or_teams_do_not_become_nonblocking(self):
        for changes in [dict(source_snapshot_sha256={'Ligue_1':'bad'}),dict(home_id='wrong'),
                        dict(recorded_at_utc='2026-10-26T19:00:00Z')]:
            _,audit=runtime.normalize_settlement_sources(self.state,{'understat:32010':dict(self.forecast,**changes)},self.sources)
            self.assertEqual(audit['nonblocking_abstentions'],[])
        altered=copy.deepcopy(self.sources);altered['Ligue_1']['dates'][0]['h']['id']='wrong'
        _,audit=runtime.normalize_settlement_sources(self.state,{'understat:32010':self.forecast},altered)
        self.assertEqual(audit['nonblocking_abstentions'],[])

    def test_conflicting_calendar_is_rejected_before_future_forecast(self):
        good=dict(self.forecast,fixture_id='understat:good')
        sources=copy.deepcopy(self.sources)
        sources['Ligue_1']['dates'].append(dict(self.initial,id='good',datetime='2026-10-25 17:15:00'))
        accepted,rejected=runtime.screen_candidates([self.forecast,good],sources)
        self.assertEqual(accepted,[good]);self.assertEqual(rejected[0]['reason'],'schedule_conflict_before_capture')
        self.assertEqual(rejected[0]['fixture_id'],'understat:32010')

    def test_manifest_and_local_execution_guard(self):
        for name in ['paper_simulation','paper_positive15']:
            reg=json.loads((runtime.v1.ROOT/name/'registration.json').read_text(encoding='utf8'))
            runtime.verify_amendment(name,reg)
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}),patch('sys.argv',['runtime','--experiment','paper_simulation']):
            with self.assertRaisesRegex(ValueError,'GitHub Actions only'):runtime.main()

    def test_original_collectors_keep_abstention_unsettled_and_block_engaged_bet(self):
        code='''
import sys,json,importlib,copy
from pathlib import Path
from production.paper_settlement_runtime_v2 import normalize_settlement_sources,settle_normalized
experiment,state,f,s=sys.argv[1:];f=json.loads(f);s=json.loads(s)
sys.path.insert(0,str(Path.cwd()/experiment));collector=importlib.import_module('run_paper');collector.check_registration()
class Journal:
 def records(self,kind):return {f['fixture_id']:f} if kind=='forecast' else {}
 def append(self,*args):raise AssertionError('Unexpected settlement')
j=Journal();metadata={'Ligue_1':{'retrieved_at_utc':'2026-10-26T11:00:00Z','url':'test','sha256':'test'}}
for engaged in [False,True]:
 if engaged:f['portfolios']['candidate']={'stake':1,'outcome':'draw','odds':3}
 normalized,audit=normalize_settlement_sources(Path(state),j.records('forecast'),s)
 count,issues=settle_normalized(collector.settle,j,normalized,metadata,audit)
 assert count==0
 assert len(issues)==int(engaged),(engaged,issues)
'''
        for experiment in ['paper_simulation','paper_positive15']:
            subprocess.run([sys.executable,'-c',code,experiment,str(self.state),json.dumps(self.forecast),json.dumps(self.sources)],
                           cwd=runtime.v1.ROOT,check=True,timeout=30)


if __name__=='__main__':unittest.main()
