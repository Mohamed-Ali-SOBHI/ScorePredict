from __future__ import annotations

import unittest
from datetime import datetime, timezone

import pandas as pd

from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME
from inference.result_monitor import (
    settle_due_predictions,
    understat_finished_results,
    update_public_snapshot,
)


class ResultMonitorTests(unittest.TestCase):
    @staticmethod
    def _ledger() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "snapshot_key": "ipswich-draw",
                    "portfolio_name": DEFAULT_PORTFOLIO_NAME,
                    "date": "2026-08-22 16:00:00",
                    "league": "EPL",
                    "team_name": "Ipswich",
                    "opponent_name": "Sunderland",
                    "selected_outcome": "draw",
                    "selected_odds": 3.5,
                    "stake_eur": 2.5,
                    "recommended": True,
                    "result_status": "pending",
                }
            ]
        )

    @staticmethod
    def _official(status: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "league": "EPL",
                    "home_team_norm": "ipswich",
                    "away_team_norm": "sunderland",
                    "official_date": pd.Timestamp("2026-08-22 16:00:00"),
                    "status": status,
                    "home_score": 1,
                    "away_score": 1,
                }
            ]
        )

    def test_second_half_is_never_treated_as_final(self) -> None:
        updated, counters = settle_due_predictions(
            self._ledger(),
            self._official("2H"),
            now=pd.Timestamp("2026-08-22 17:55:00"),
        )

        self.assertEqual(updated.iloc[0]["result_status"], "pending")
        self.assertEqual(counters["settled"], 0)
        self.assertEqual(counters["still_running"], 1)

    def test_final_status_settles_the_bet_and_profit(self) -> None:
        updated, counters = settle_due_predictions(
            self._ledger(),
            self._official("FT"),
            now=pd.Timestamp("2026-08-22 17:55:00"),
        )

        self.assertEqual(updated.iloc[0]["result_status"], "won")
        self.assertEqual(updated.iloc[0]["actual_home_score"], 1)
        self.assertEqual(updated.iloc[0]["actual_away_score"], 1)
        self.assertEqual(updated.iloc[0]["realized_profit_units"], 2.5)
        self.assertEqual(updated.iloc[0]["realized_profit"], 6.25)
        self.assertEqual(counters["settled"], 1)

    def test_elapsed_time_alone_never_settles_before_check_window(self) -> None:
        updated, counters = settle_due_predictions(
            self._ledger(),
            self._official("FT"),
            now=pd.Timestamp("2026-08-22 17:30:00"),
        )

        self.assertEqual(updated.iloc[0]["result_status"], "pending")
        self.assertEqual(counters["due"], 0)

    def test_understat_history_is_a_finished_result_fallback(self) -> None:
        payload = {
            "1": {
                "title": "Ipswich Town",
                "history": [
                    {
                        "h_a": "h",
                        "date": "2026-08-22 16:00:00",
                        "result": "d",
                        "scored": 1,
                        "missed": 1,
                        "xG": 1.2,
                        "xGA": 0.9,
                    }
                ],
            },
            "2": {
                "title": "Sunderland",
                "history": [
                    {
                        "h_a": "a",
                        "date": "2026-08-22 16:00:00",
                        "result": "d",
                        "scored": 1,
                        "missed": 1,
                        "xG": 0.9,
                        "xGA": 1.2,
                    }
                ],
            },
        }

        results = understat_finished_results(payload, league="EPL")

        self.assertEqual(len(results), 1)
        self.assertEqual(results.iloc[0]["status"], "FT")
        self.assertEqual(results.iloc[0]["home_team_norm"], "ipswich")

    def test_snapshot_moves_a_finished_match_out_of_upcoming_cards(self) -> None:
        ledger, _ = settle_due_predictions(
            self._ledger(),
            self._official("FT"),
            now=pd.Timestamp("2026-08-22 17:55:00"),
        )
        snapshot = {
            "meta": {"activePortfolio": DEFAULT_PORTFOLIO_NAME},
            "summary": {"upcomingBets": 1},
            "tracking": {},
            "performance": {"live": {}},
            "predictions": [
                {
                    "date": "2026-08-22T16:00:00+02:00",
                    "homeTeam": "Ipswich",
                    "awayTeam": "Sunderland",
                }
            ],
            "activity": [
                {
                    "date": "2026-08-22T16:00:00+02:00",
                    "homeTeam": "Ipswich",
                    "awayTeam": "Sunderland",
                    "status": "pending",
                }
            ],
        }

        patched = update_public_snapshot(
            snapshot,
            ledger,
            portfolio_name=DEFAULT_PORTFOLIO_NAME,
            generated_at=datetime(2026, 8, 22, 16, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(patched["predictions"], [])
        self.assertEqual(patched["activity"][0]["status"], "won")
        self.assertEqual(patched["activity"][0]["actualScore"], "1 - 1")
        self.assertEqual(patched["tracking"]["verified"], 1)
        self.assertEqual(patched["summary"]["liveProfitUnits"], 2.5)


if __name__ == "__main__":
    unittest.main()
