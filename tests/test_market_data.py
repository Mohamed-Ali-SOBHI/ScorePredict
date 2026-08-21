from __future__ import annotations

import unittest

from data_pipeline.market_data import normalize_team_name


class MarketDataTests(unittest.TestCase):
    def test_current_la_liga_market_aliases(self) -> None:
        expected_names = {
            "Atl. Madrid": "atletico madrid",
            "Dep. A Coruna": "deportivo la coruna",
            "Santander": "racing santander",
        }

        for source_name, expected_name in expected_names.items():
            with self.subTest(source_name=source_name):
                self.assertEqual(normalize_team_name(source_name), expected_name)


if __name__ == "__main__":
    unittest.main()
