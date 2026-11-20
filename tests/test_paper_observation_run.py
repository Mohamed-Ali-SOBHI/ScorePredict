import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from production.paper_observation_run import AVAILABILITY, CATALOG, PAUSED, prepare


class PaperObservationRun(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cache = Path(temp.name)
        self.directory = self.cache / '123'
        self.probe = self.directory / AVAILABILITY
        self.probe.parent.mkdir(parents=True)
        self.leagues = ['Bundesliga', 'EPL', 'Serie_A', 'Ligue_1', 'La_liga']
        self.hashes = {AVAILABILITY: 'verified-by-collector'}
        self.collector = Mock(CACHE=self.cache)
        self.collector.production_snapshot.side_effect = ValueError('Missing/ambiguous evidence file: ' + CATALOG)

    def write_probe(self, mode='price_only', age=0):
        at = datetime.now(timezone.utc) - timedelta(hours=age)
        sources = [dict(league=league, available=mode == 'normal', reason='understat_maintenance_page')
                   for league in self.leagues]
        self.probe.write_text(json.dumps(dict(mode=mode, checkedAt=at.isoformat(), sources=sources)))
        (self.directory / 'verified_files.json').write_text(json.dumps(self.hashes))

    def test_verified_fallback_without_calendar_defers(self):
        self.write_probe()
        snapshot, pause = prepare(self.collector, {})
        self.assertIsNone(snapshot)
        self.assertEqual((pause['state'], pause['production_run_id'], pause['new_forecasts']), (PAUSED, '123', 0))
        self.assertEqual(set(pause['sources']), set(self.leagues))

    def test_unexpected_missing_ambiguous_or_stale_inputs_still_fail(self):
        self.write_probe('normal')
        with self.assertRaisesRegex(ValueError, 'Missing/ambiguous'):
            prepare(self.collector, {})
        self.write_probe(age=25)
        with self.assertRaisesRegex(ValueError, 'stale'):
            prepare(self.collector, {})
        self.hashes.update({'a/' + CATALOG: 'one', 'b/' + CATALOG: 'two'})
        self.write_probe()
        with self.assertRaisesRegex(ValueError, 'Missing/ambiguous'):
            prepare(self.collector, {})

    def test_full_run_uses_verified_snapshot_and_propagates_integrity_errors(self):
        self.write_probe('normal')
        snapshot = ({'databaseId': 123}, self.directory / CATALOG, self.directory / 'ledger.csv', self.hashes)
        self.collector.production_snapshot.side_effect = None
        self.collector.production_snapshot.return_value = snapshot
        self.assertEqual(prepare(self.collector, {}), (snapshot, None))
        self.collector.production_snapshot.side_effect = ValueError('Downloaded source snapshot altered')
        with self.assertRaisesRegex(ValueError, 'altered'):
            prepare(self.collector, {})
