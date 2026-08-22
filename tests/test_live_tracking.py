from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from inference.live_tracking import append_tracking_rows, build_tracking_rows


class LiveTrackingTests(unittest.TestCase):
    def test_pending_prediction_refreshes_only_the_kickoff_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.csv"
            first_bet = pd.DataFrame(
                [
                    {
                        "date": "2026-08-22 10:00:00",
                        "league": "EPL",
                        "team_name": "Ipswich",
                        "opponent_name": "Sunderland",
                        "selected_outcome": "draw",
                        "selected_odds": 3.5,
                        "recommended_bet": True,
                    }
                ]
            )
            corrected_bet = first_bet.copy()
            corrected_bet.loc[0, "date"] = "2026-08-22 16:00:00"
            corrected_bet.loc[0, "selected_odds"] = 3.7

            append_tracking_rows(build_tracking_rows(first_bet, portfolio_name="portfolio"), ledger)
            append_tracking_rows(build_tracking_rows(corrected_bet, portfolio_name="portfolio"), ledger)

            saved = pd.read_csv(ledger)
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved.iloc[0]["date"], "2026-08-22 16:00:00")
            self.assertEqual(saved.iloc[0]["selected_odds"], 3.5)


if __name__ == "__main__":
    unittest.main()
