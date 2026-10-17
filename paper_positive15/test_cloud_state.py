import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cloud_state
import run_paper
from paper_core import Journal, utcnow


class CloudStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registration = {'registered_at_utc':utcnow().isoformat()}
        for target in ['cloud_state.STATE', 'run_paper.STATE']:
            p = patch(target, self.root); p.start(); self.addCleanup(p.stop)
        p = patch('cloud_state.check_registration', return_value=self.registration)
        p.start(); self.addCleanup(p.stop)
        journal = Journal(self.root/'journal.sqlite3', self.registration)
        journal.append('run', 'first', {'test':True})
        journal.db.close()
        run_paper.write(self.root/'last_run.json', {'state':'collected', 'finished_at_utc':utcnow().isoformat()})
        cloud_state.seal()

    def test_checkpoint_survives_append_and_rejects_corruption(self):
        _, prefix = cloud_state.verify()
        journal = Journal(self.root/'journal.sqlite3', self.registration)
        journal.append('run', 'second', {'test':True})
        journal.db.close()
        cloud_state.seal(prefix)
        _, events = cloud_state.verify()
        self.assertEqual(events[:len(prefix)], prefix)
        self.assertEqual(len(events), 2)
        (self.root/'evidence.json').write_text('{}')
        with self.assertRaises(ValueError):cloud_state.verify()

    def test_missing_journal_cannot_restart(self):
        (self.root/'journal.sqlite3').unlink()
        with self.assertRaises(ValueError):cloud_state.verify()
        self.assertFalse((self.root/'journal.sqlite3').exists())

    def test_prior_event_cannot_disappear(self):
        _, prefix = cloud_state.verify()
        with self.assertRaises(ValueError):cloud_state.seal(prefix+prefix)

    def test_failed_capture_does_not_display_old_success(self):
        cloud_state.seal(outcome='failure')
        report = json.loads((self.root/'report.json').read_text())
        self.assertEqual(report['status']['state'], 'collection_failed')
        cloud_state.verify()

    def test_live_run_refuses_local_execution(self):
        with patch.dict('os.environ', {'GITHUB_ACTIONS':'false'}):
            with self.assertRaises(ValueError):run_paper.main()


if __name__ == '__main__':unittest.main()
