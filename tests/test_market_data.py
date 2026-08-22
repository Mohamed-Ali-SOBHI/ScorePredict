from __future__ import annotations

import unittest

from data_pipeline.market_data import (
    MarketDataUnavailableError,
    normalize_team_name,
    parse_market_csv_text,
)


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

    def test_rejects_an_html_multiple_choices_page(self) -> None:
        html = "<!DOCTYPE HTML><html><title>300 Multiple Choices</title></html>"

        with self.assertRaisesRegex(MarketDataUnavailableError, "unavailable"):
            parse_market_csv_text(html, "https://example.test/E0.csv")

    def test_accepts_a_minimal_valid_market_csv(self) -> None:
        csv_text = "Date,HomeTeam,AwayTeam,HS,AS,B365H,B365D,B365A\n21/08/2026,Arsenal,Coventry,10,5,1.2,7.9,20.0\n"

        frame = parse_market_csv_text(csv_text, "https://example.test/E0.csv")

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["HomeTeam"], "Arsenal")


if __name__ == "__main__":
    unittest.main()
