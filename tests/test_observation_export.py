import copy,json,tempfile,unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from production import observation_export as ex

class ObservationExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.source=root/'source';self.source.mkdir();self.comparison=root/'comparison'
        self.c=ex.adapter();c=self.c
        import run_paper
        for module,field,value in [(c,'STATE',self.comparison),(c.source_state,'STATE',self.source),(run_paper,'STATE',self.source)]:
            p=patch.object(module,field,value);p.start();self.addCleanup(p.stop)
        now=c.utcnow();created=now-timedelta(minutes=2);source_reg=c.source_state.check_registration();self.reg=c.check_registration()
        p={'local_price_only':{'away':.4,'draw':.2,'home':.4},'local_sport_only':{'away':.2,'draw':.6,'home':.2}}
        odds={'away':4.,'draw':4.,'home':4.};choices=c.pc.decisions('EPL',p,odds)
        self.f={'fixture_id':'test-only:1','registration_sha256':c.digest(source_reg),'league':'EPL','home_team':'Home','away_team':'Away',
            'recorded_at_utc':created.isoformat(),'kickoff_utc':(now+timedelta(hours=10)).isoformat(),
            'quotes_collected_at_utc':created.isoformat(),'sports_collected_at_utc':created.isoformat(),
            'production_snapshot_completed_at_utc':created.isoformat(),'reference':None,'probabilities':p,'odds':odds,
            'decisions':choices,'portfolios':c.pc.allocations(None,choices)}
        j=c.pc.Journal(self.source/'journal.sqlite3',source_reg);j.append('forecast',self.f['fixture_id'],self.f);j.db.close()
        c.source_state.write(self.source/'last_run.json',{'state':'collected','finished_at_utc':now.isoformat()});c.source_state.seal()
        c.initialize()
        receipt={'type':'forecast','fixture_id':self.f['fixture_id'],'registration_sha256':c.digest(self.reg),
            'recorded_at_utc':now.isoformat(),'source_forecast':self.f,'source_forecast_sha256':c.digest(self.f),
            'portfolios':c.project(self.f,self.reg['nine_members'])}
        j=c.Journal(self.comparison/'journal.sqlite3',self.reg);j.forecast(receipt)
        c.seal(j,{'state':'collected','finished_at_utc':now.isoformat()},[],c.source_state.verify()[0]);j.close()
        self.receipt=receipt;self.now=now;self.source_reg=source_reg

    def test_one_union_ticket_but_each_strategy_tracked(self):
        data=ex.build(self.source,self.comparison)
        self.assertEqual(data['status'],'ready');self.assertEqual(len(data['strategies']),9)
        self.assertEqual(len(data['tickets']),1);self.assertEqual(data['tickets'][0]['outcome'],'home')
        self.assertEqual(data['live']['union']['pending'],1);self.assertIsNone(data['live']['union']['roi'])
        self.assertEqual(sum(m['pending'] for m in data['live']['individual'].values()),2)
        self.assertEqual(data['live']['union']['profit'],0)
        self.assertEqual(data['history']['periods']['season']['union']['profit'],34.52)

    def test_settlement_uses_frozen_odds_and_excludes_pending(self):
        c=self.c;later=self.now+timedelta(hours=13)
        s={'forecast_sha256':c.digest(self.f),'result_seen_at_utc':later.isoformat(),'home_goals':1,'away_goals':0,'outcome':'home'}
        j=c.pc.Journal(self.source/'journal.sqlite3',self.source_reg)
        with patch.object(c.pc,'utcnow',return_value=later):j.append('settlement',self.f['fixture_id'],s)
        j.db.close();c.source_state.seal()
        _,prior=c.verify();j=c.Journal(self.comparison/'journal.sqlite3',self.reg)
        with patch.object(c,'utcnow',return_value=later):j.settlement({'type':'settlement','fixture_id':self.f['fixture_id'],
            'forecast_sha256':c.digest(self.receipt),'source_settlement':s})
        c.seal(j,{'state':'collected','finished_at_utc':later.isoformat()},prior,c.source_state.verify()[0]);j.close()
        data=ex.build(self.source,self.comparison)
        self.assertEqual(data['live']['union']['settled'],1);self.assertEqual(data['live']['union']['pending'],0)
        self.assertEqual(data['live']['union']['profit'],3);self.assertEqual(data['live']['union']['roi'],3)
        self.assertEqual(data['tickets'][0]['odds'],4)

    def test_changed_metrics_or_missing_journal_rejected(self):
        (self.comparison/'report.json').write_text('{}')
        with self.assertRaises(ValueError):ex.build(self.source,self.comparison)
        (self.source/'journal.sqlite3').unlink()
        with self.assertRaises(ValueError):ex.build(self.source,self.comparison)

    def test_changed_source_does_not_publish_trustworthy_gains(self):
        (self.source/'evidence.json').write_text('{}')
        with self.assertRaises(ValueError):ex.build(self.source,self.comparison)

    def test_unavailable_export_never_reports_zero_as_a_verified_result(self):
        target=Path(self.temp.name)/'failed.json'
        with patch('sys.argv',['observation_export','--output',str(target)]),patch.object(ex,'fetch_state',side_effect=RuntimeError('test outage')):
            ex.main()
        data=ex.read(target)
        self.assertEqual(data['status'],'unavailable');self.assertIsNone(data['live']);self.assertEqual(data['tickets'],[])

    def test_observation_is_not_published(self):
        for name in ['daily-predictions.yml','results-monitor.yml','ui-only-publication.yml']:
            workflow=(ex.ROOT/'.github/workflows'/name).read_text(encoding='utf8')
            self.assertNotIn('-m production.observation_export',workflow)
        public=ex.ROOT/'production/static'
        self.assertFalse(list(public.rglob('*observation*')))
        for page in public.glob('*.html'):
            self.assertNotIn('observation.html',page.read_text(encoding='utf8'))
        self.assertFalse(ex.OUTPUT.resolve().is_relative_to(public.resolve()))

    def test_export_cannot_write_into_public_site(self):
        with self.assertRaises(ValueError):
            ex.require_private_output(ex.ROOT/'production/static/data/observation.json')

if __name__=='__main__':unittest.main()
