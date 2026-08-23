from __future__ import annotations

import unittest

import pandas as pd

from inference.evaluate_live_portfolio import build_summary, evaluate_rows, prepare_ledger
from inference.portfolio_presets import PRODUCTION_PORTFOLIO_NAME


class TerminalResultImmutabilityTests(unittest.TestCase):
    def test_confirmed_result_survives_a_stale_batch_refresh(self) -> None:
        ledger = pd.DataFrame(
            [
                {
                    "date": "2026-08-22 16:00:00",
                    "league": "EPL",
                    "team_name": "Ipswich",
                    "opponent_name": "Sunderland",
                    "selected_outcome": "draw",
                    "selected_odds": 3.5,
                    "stake_eur": 2.5,
                    "portfolio_name": PRODUCTION_PORTFOLIO_NAME,
                    "recommended": True,
                    "result_status": "lost",
                    "actual_result": "w",
                    "actual_outcome": "home_win",
                    "actual_home_score": 2,
                    "actual_away_score": 1,
                    "match_found": True,
                    "won_live_bet": False,
                    "realized_profit_units": -1.0,
                    "realized_profit": -2.5,
                }
            ]
        )
        stale_results = pd.DataFrame(
            [
                {
                    "league": "EPL",
                    "match_date": pd.Timestamp("2026-05-24"),
                    "home_team_norm": "arsenal",
                    "away_team_norm": "liverpool",
                    "actual_outcome": "draw",
                }
            ]
        )

        prepared = prepare_ledger(
            ledger,
            pd.Timestamp("2026-08-12"),
            portfolio_name=PRODUCTION_PORTFOLIO_NAME,
        )
        evaluated = evaluate_rows(
            prepared,
            stale_results,
            as_of_date=pd.Timestamp("2026-08-23 20:00:00"),
        )
        summary = build_summary(
            evaluated,
            freeze_date="2026-08-12",
            as_of_date="2026-08-23",
            portfolio_name=PRODUCTION_PORTFOLIO_NAME,
        )

        self.assertEqual(evaluated.iloc[0]["result_status"], "lost")
        self.assertEqual(evaluated.iloc[0]["actual_home_score"], 2)
        self.assertEqual(evaluated.iloc[0]["actual_away_score"], 1)
        self.assertEqual(evaluated.iloc[0]["realized_profit_units"], -1.0)
        self.assertEqual(summary["settled_bets"], 1)
        self.assertEqual(summary["lost_bets"], 1)
        self.assertEqual(summary["profit_units"], -1.0)


if __name__ == "__main__":
    unittest.main()
