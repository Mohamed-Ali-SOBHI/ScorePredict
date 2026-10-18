from datetime import datetime, timezone, timedelta
import copy
import json
from pathlib import Path
import tempfile
import sqlite3
import hashlib
import unittest
from unittest.mock import patch

from production import english_away_export as english
from production import observation_personal as personal


class EnglishAwayObservationTests(unittest.TestCase):
    def setUp(self):
        self.activation=datetime(2026,10,18,15,tzinfo=timezone.utc)
        self.now=self.activation+timedelta(days=2)
        self.reg={'strategy_id':'epl_away_logit_strict_2026_10_18',
            'registered_at_utc':self.activation.isoformat(),'source_registration_sha256':'source-version',
            'source_prefix':{'event_count':0,'events_sha256':english.digest([])},'rule':english.RULE,
            'retrospective_history':{'standalone':{'bets':12,'profit':7.8,'roi':.65},
                'with_public_bundesliga':{'bets':22,'profit':10.5,'roi':10.5/22}}}
        self.status={'state':'collected','finished_at_utc':self.now.isoformat()}

    def forecast(self,identity='english-1',league='EPL',price=3.,probability=.4):
        created=self.activation+timedelta(hours=1)
        return {'fixture_id':identity,'league':league,'recorded_at_utc':created.isoformat(),
            'kickoff_utc':(created+timedelta(hours=4)).isoformat(),
            'quotes_collected_at_utc':created.isoformat(),'registration_sha256':'source-version',
            'home_team':'Home','away_team':'Away','reference':None,
            'odds':{'away':price,'draw':3.4,'home':2.3},
            'probabilities':{'logit_sports':{'away':probability,'draw':.25,'home':.75-probability}}}

    def events(self,records):
        events=[];prior=self.reg['source_registration_sha256']
        for kind,identity,payload in records:
            value={'kind':kind,'identity':identity,'payload':payload,'previous_hash':prior}
            prior=english.digest(value)
            events.append(dict(seq=len(events)+1,**value,event_hash=prior))
        return events

    def build(self,records):
        events=self.events(records)
        return english.build(events,{'events_sha256':english.digest(events)},self.status,self.reg,self.now)

    def test_new_pending_selection_is_one_unit_and_not_a_settled_return(self):
        report=self.build([('forecast','english-1',self.forecast())])
        self.assertEqual(report['metrics']['pending'],1)
        self.assertEqual(report['metrics']['settled'],0)
        self.assertIsNone(report['metrics']['roi'])
        self.assertEqual(report['tickets'][0]['stake'],1)
        self.assertEqual(report['union'],report['metrics'])

    def test_strict_price_and_ev_filters(self):
        for price,probability,expected in [(2.,.7,1),(6.,.25,1),(1.99,.7,0),(6.01,.25,0),(3.,.36,0)]:
            with self.subTest(price=price,probability=probability):
                report=self.build([('forecast','english-1',self.forecast(price=price,probability=probability))])
                self.assertEqual(report['metrics']['pending'],expected)

    def test_old_source_forecasts_are_never_backfilled_even_before_kickoff(self):
        old=self.forecast();old['recorded_at_utc']=(self.activation-timedelta(minutes=1)).isoformat()
        self.assertEqual(self.build([('forecast','english-1',old)])['tickets'],[])
        old=self.forecast();events=self.events([('forecast','english-1',old)])
        self.reg['source_prefix']={'event_count':1,'events_sha256':english.digest(events)}
        report=english.build(events,{'events_sha256':english.digest(events)},self.status,self.reg,self.now)
        self.assertEqual(report['tickets'],[])

    def test_confirmation_uses_original_quote_and_deduplicated_union(self):
        f=self.forecast();result={'forecast_sha256':english.digest(f),'outcome':'away','home_goals':0,'away_goals':1,
            'result_seen_at_utc':(self.activation+timedelta(days=1)).isoformat()}
        report=self.build([('forecast','english-1',f),('settlement','english-1',result)])
        self.assertEqual(report['metrics']['profit'],2)
        self.assertEqual(report['metrics']['roi'],2)
        baseline={'fixture_id':'same','outcome':'draw','odds':4}
        addition={'fixture_id':'same','outcome':'away','odds':3}
        self.assertEqual(english.union_tickets([baseline],[addition]),[baseline])

    def test_changed_forecast_or_result_rejected(self):
        events=self.events([('forecast','english-1',self.forecast())])
        events[0]['payload']['odds']['away']=4.
        with self.assertRaises(ValueError):
            english.build(events,{},self.status,self.reg,self.now)
        f=self.forecast();bad={'forecast_sha256':'changed','outcome':'away','home_goals':0,'away_goals':1,
            'result_seen_at_utc':self.now.isoformat()}
        with self.assertRaises(ValueError):self.build([('forecast','english-1',f),('settlement','english-1',bad)])

    def test_source_prefix_and_capture_timing_must_match(self):
        f=self.forecast();f['kickoff_utc']=f['recorded_at_utc']
        with self.assertRaises(ValueError):self.build([('forecast','english-1',f)])
        self.reg['source_prefix']={'event_count':1,'events_sha256':'wrong'}
        with self.assertRaises(ValueError):self.build([('forecast','english-1',self.forecast())])

    def test_public_bundesliga_reference_stays_separate_and_retains_its_quote(self):
        b=self.forecast(identity='bundes-1',league='Bundesliga')
        b['reference']={'outcome':'draw','odds':4.27,'generated_at_utc':b['recorded_at_utc']}
        report=self.build([('forecast','bundes-1',b),('forecast','english-1',self.forecast())])
        self.assertEqual(report['metrics']['pending'],1)
        self.assertEqual(report['baseline']['pending'],1)
        self.assertEqual(report['union']['pending'],2)
        self.assertEqual(next(t['odds'] for t in report['unionTickets'] if t['strategy']=='reference'),4.27)

    def test_unavailable_source_never_claims_a_verified_zero(self):
        with patch.object(english,'read_registration',side_effect=ValueError('altered')):
            data=english.snapshot()
        self.assertEqual(data['status'],'unavailable')
        self.assertNotIn('metrics',data)

    def test_personal_section_separates_simulation_and_escapes_teams(self):
        f=self.forecast();f['home_team']='<script>alert(1)</script>'
        data=self.build([('forecast','english-1',f)])
        html=personal.english_section(data)
        self.assertIn('Total Bundesliga + E02 · sans doublon',html)
        self.assertIn('historique séparé',html)
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertIn('&lt;script&gt;',html)

    def test_read_only_verification_releases_database_and_rejects_changed_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            source=english.ex.read(english.ex.ROOT/'paper_simulation/registration.json')
            source_hash=english.digest(source)
            (folder/'registration.json').write_text(json.dumps(source),encoding='utf8')
            (folder/'evidence.json').write_text(json.dumps({'registration_sha256':source_hash,'events':[]}),encoding='utf8')
            (folder/'report.json').write_text(json.dumps({'status':self.status}),encoding='utf8')
            db=sqlite3.connect(folder/'journal.sqlite3')
            db.execute('CREATE TABLE events(seq INTEGER,kind TEXT,identity TEXT,payload TEXT,previous_hash TEXT,event_hash TEXT)')
            db.commit();db.close()
            files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
            checkpoint={'registration_sha256':source_hash,'events_sha256':english.digest([]),'event_count':0,'files':files}
            (folder/'checkpoint.json').write_text(json.dumps(checkpoint),encoding='utf8')
            config={'source_registration_sha256':source_hash}
            events,_,_=english.verify_source(folder,config)
            self.assertEqual(events,[])
            # In particular this must not leave an SQLite handle open on Windows.
            (folder/'journal.sqlite3').unlink()
            with self.assertRaises(ValueError):english.verify_source(folder,config)


if __name__=='__main__':unittest.main()
