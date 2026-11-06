import copy
from datetime import datetime, timezone
import unittest

from production.recover_bundesliga import read_archive, verify_coverage


class ManualRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.payload = read_archive()
        self.now = datetime(2026, 11, 6, 19, 0, tzinfo=timezone.utc)
        self.results = [dict(Date=datetime.fromisoformat(g['datetime']).strftime('%d/%m/%Y'),
                             HomeTeam=g['h']['title'], AwayTeam=g['a']['title'],
                             FTHG=str(g['goals']['h']), FTAG=str(g['goals']['a']))
                        for g in self.payload['dates'] if g['isResult'] is True]

    def test_original_archive_has_all_72_results_and_retains_capture_date(self):
        original = copy.deepcopy(self.payload)
        self.assertEqual(verify_coverage(self.payload, self.results, self.now), 72)
        self.assertEqual(self.payload, original)
        self.assertTrue(self.payload['captured_at'].startswith('2026-11-01'))

    def test_new_result_missing_from_archive_blocks_recovery(self):
        rows = self.results + [dict(Date='06/11/2026', HomeTeam='Unknown', AwayTeam='Other', FTHG='0', FTAG='0')]
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            verify_coverage(self.payload, rows, self.now)

    def test_disagreement_duplicates_and_missing_result_feed_block(self):
        changed = copy.deepcopy(self.results); changed[0]['FTHG'] = '99'
        for rows in [changed, self.results + [self.results[0]], [], self.results[:-1]]:
            with self.assertRaises(ValueError):
                verify_coverage(self.payload, rows, self.now)

    def test_stale_results_feed_cannot_revalidate_old_cache_after_match(self):
        with self.assertRaisesRegex(ValueError, 'Scheduled match now due'):
            verify_coverage(self.payload, self.results, datetime(2026,11,7,8,tzinfo=timezone.utc))


if __name__ == '__main__':
    unittest.main()
