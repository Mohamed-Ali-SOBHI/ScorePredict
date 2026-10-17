import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
import compare9 as c


def sample(league='EPL'):
    now=c.utcnow();source_reg=c.read(c.SOURCE/'registration.json')
    reg=c.read(c.ROOT/'registration.json')|{'registered_at_utc':(now-timedelta(minutes=1)).isoformat()}
    created=now-timedelta(minutes=2)
    if league=='EPL':
        probs={'local_price_only':{'away':.4,'draw':.2,'home':.4},'local_sport_only':{'away':.2,'draw':.6,'home':.2}}
    else:probs={m['model']:{'away':.3,'draw':.4,'home':.3} for m in c.pc.MEMBERS if m['league']==league}
    odds={'away':4.,'draw':4.,'home':4.};choices=c.pc.decisions(league,probs,odds)
    reference=None if league=='EPL' else {'outcome':'draw','odds':4.,'generated_at_utc':created.isoformat(),'source':'frozen_Bundesliga_anchor'}
    f={'fixture_id':'test:1','registration_sha256':c.digest(source_reg),'league':league,'home_team':'Home','away_team':'Away',
       'recorded_at_utc':created.isoformat(),'kickoff_utc':(now+timedelta(hours=10)).isoformat(),
       'quotes_collected_at_utc':created.isoformat(),'sports_collected_at_utc':created.isoformat(),'production_snapshot_completed_at_utc':created.isoformat(),
       'reference':reference,'probabilities':probs,'odds':odds,'decisions':choices,'portfolios':c.pc.allocations(reference,choices)}
    r={'type':'forecast','fixture_id':f['fixture_id'],'registration_sha256':c.digest(reg),'recorded_at_utc':now.isoformat(),
       'source_forecast':f,'source_forecast_sha256':c.digest(f),'portfolios':c.project(f,reg['nine_members'])}
    return reg,r,now


class ComparisonTests(unittest.TestCase):
    def test_exact_nine_and_frozen_parent_order(self):
        reg=c.check_registration();selected=c.read(c.ROOT/'selection_provenance.json')['selected_ids']
        self.assertEqual(len(reg['nine_members']),9)
        self.assertEqual(reg['nine_members'],selected)
        self.assertNotIn('local_sport_only|EPL|draw|0.10|all',selected)

    def test_conflicting_outcomes_and_duplicates(self):
        reg,r,now=sample();c.validate_forecast(r,reg,now)
        nine=r['portfolios']['bundesliga_plus9'];fifteen=r['portfolios']['bundesliga_plus15']
        self.assertEqual(nine['outcome'],'home')
        self.assertEqual(fifteen['outcome'],'draw')
        self.assertEqual(nine['stake'],1)
        self.assertEqual(nine['odds'],r['source_forecast']['odds']['home'])
        rows,tickets,diff=c.metrics({'test:1':r},{})
        self.assertEqual(diff['different_outcome'],1)
        self.assertEqual(rows[1]['pending_bets'],1)
        self.assertEqual(rows[2]['pending_bets'],1)

    def test_bundesliga_priority(self):
        reg,r,now=sample('Bundesliga');c.validate_forecast(r,reg,now)
        for bet in r['portfolios'].values():
            self.assertEqual(bet,{'source':'reference','outcome':'draw','odds':4.,'stake':1.})

    def test_no_started_matches_or_retroactive_enrollment(self):
        reg,r,now=sample()
        for delta in [-timedelta(hours=2),timedelta(minutes=4),timedelta(hours=25)]:
            with self.assertRaises(ValueError):c.validate_forecast(r,reg,stamp_now(r,delta,now))
        bad=copy.deepcopy(r);bad['recorded_at_utc']=(c.stamp(reg['registered_at_utc'])-timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):c.validate_forecast(bad,reg,now)

    def test_no_odds_or_reference_replacement(self):
        reg,r,now=sample();bad=copy.deepcopy(r);bad['portfolios']['bundesliga_plus9']['odds']=10
        with self.assertRaises(ValueError):c.validate_forecast(bad,reg,now)
        bad=copy.deepcopy(r);bad['source_forecast']['odds']['home']=10
        with self.assertRaises(ValueError):c.validate_forecast(bad,reg,now)

    def test_append_only_idempotent_and_settlement(self):
        reg,r,now=sample()
        with tempfile.TemporaryDirectory() as tmp:
            j=c.Journal(Path(tmp)/'journal.sqlite3',reg)
            self.assertTrue(j.forecast(r));self.assertFalse(j.forecast(r))
            bad=copy.deepcopy(r);bad['portfolios']['bundesliga_plus9']['stake']=2
            with self.assertRaises(ValueError):j.forecast(bad)
            with self.assertRaises(sqlite3.IntegrityError):j.store.db.execute('DELETE FROM events')
            j.store.db.rollback()
            later=now+timedelta(hours=13)
            settlement={'type':'settlement','fixture_id':r['fixture_id'],'forecast_sha256':c.digest(r),
                'source_settlement':{'forecast_sha256':r['source_forecast_sha256'],'result_seen_at_utc':later.isoformat(),
                    'home_goals':1,'away_goals':0,'outcome':'home'}}
            with self.assertRaises(ValueError):j.settlement(settlement)
            with patch('compare9.utcnow',return_value=later):self.assertTrue(j.settlement(settlement))
            rows,tickets,diff=c.metrics(j.records('forecast'),j.records('settlement'))
            self.assertEqual(rows[1]['profit'],3)
            self.assertEqual(rows[2]['profit'],-1)
            self.assertEqual(diff['profit_9_minus_15'],4)
            j.close()

    def test_missing_or_corrupted_journal_and_failure_seal(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'new_state'
            with patch('compare9.STATE',state):
                c.initialize();checkpoint,prior=c.verify()
                j=c.Journal(state/'journal.sqlite3',c.check_registration())
                status={'state':'collection_failed','finished_at_utc':c.utcnow().isoformat()}
                c.seal(j,status,prior);j.close();c.verify()
                self.assertEqual(c.read(state/'report.json')['status']['state'],'collection_failed')
                (state/'tickets.json').write_text('[] ')
                with self.assertRaises(ValueError):c.verify()
                (state/'journal.sqlite3').unlink()
                with self.assertRaises(ValueError):c.verify()

    def test_local_collection_refused(self):
        with patch.dict('os.environ',{'GITHUB_ACTIONS':'false'}):
            with self.assertRaises(ValueError):c.collect()


def stamp_now(receipt,remaining,now):
    # Alter the evaluation instant; source receipt remains immutable.
    return c.stamp(receipt['source_forecast']['kickoff_utc'])-remaining


if __name__=='__main__':unittest.main(verbosity=2)
