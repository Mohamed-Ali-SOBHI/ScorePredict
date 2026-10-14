import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from inference import fetch_sportytrader_portfolio_odds as collector


class CollectionWindowTests(unittest.TestCase):
    def test_collection_excludes_started_and_distant_matches_before_export(self):
        now = datetime(2026, 10, 14, 18, tzinfo=timezone.utc)
        fixtures = pd.DataFrame({
            'date': ['2026-10-14T17:59:00Z', '2026-10-15T17:59:59Z', '2026-10-15T18:00:00Z'],
            'league': ['EPL'] * 3,
            'quote_observed_at_utc': ['2026-10-14T18:00:00Z'] * 3,
            'market_draw_odds_open': [3.2, 3.5, 4.0],
        })
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'fixtures.csv'
            with patch('sys.argv', ['collect', '--next-24-hours', '--leagues', 'EPL', '--output', str(output)]), \
                 patch.object(collector, 'datetime') as clock, \
                 patch.object(collector, 'fetch_upcoming_fixtures_for_leagues', return_value=fixtures) as fetch:
                clock.now.return_value = now
                collector.main()
            kept = pd.read_csv(output)
            self.assertEqual(kept['date'].tolist(), ['2026-10-15T17:59:59Z'])
            self.assertEqual(kept['market_draw_odds_open'].tolist(), [3.5])
            self.assertEqual(kept['quote_observed_at_utc'].tolist(), ['2026-10-14T18:00:00Z'])
            self.assertEqual(fetch.call_args.kwargs['date_to'], pd.Timestamp('2026-10-15'))

    def test_explicit_catalog_dates_do_not_apply_the_prediction_limit(self):
        with patch('sys.argv', ['collect', '--date-from', '2026-10-14', '--date-to', '2026-12-14']):
            self.assertFalse(collector.parse_args().next_24_hours)
