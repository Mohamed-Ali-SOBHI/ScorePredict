from __future__ import annotations

import unittest
from datetime import datetime, timezone

import pandas as pd

from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME
from inference.result_monitor import (
    refresh_pending_dates_from_snapshot,
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

    def test_public_kickoff_repairs_stale_supabase_time_before_result_check(self) -> None:
        ledger = self._ledger()
        ledger.loc[0, "date"] = "2026-08-22 19:30:00"
        snapshot = {
            "predictions": [
                {
                    "date": "2026-08-22T16:00:00+02:00",
                    "league": "EPL",
                    "homeTeam": "Ipswich",
                    "awayTeam": "Sunderland",
                }
            ],
            "activity": [],
        }

        refreshed, count = refresh_pending_dates_from_snapshot(ledger, snapshot)

        self.assertEqual(count, 1)
        self.assertEqual(refreshed.iloc[0]["date"], "2026-08-22T16:00:00+02:00")

    def test_public_kickoff_never_rewrites_a_settled_prediction(self) -> None:
        ledger = self._ledger()
        ledger.loc[0, "date"] = "2026-08-22 19:30:00"
        ledger.loc[0, "result_status"] = "lost"
        snapshot = {
            "predictions": [],
            "activity": [
                {
                    "date": "2026-08-22T16:00:00+02:00",
                    "league": "EPL",
                    "homeTeam": "Ipswich",
                    "awayTeam": "Sunderland",
                }
            ],
        }

        refreshed, count = refresh_pending_dates_from_snapshot(ledger, snapshot)

        self.assertEqual(count, 0)
        self.assertEqual(refreshed.iloc[0]["date"], "2026-08-22 19:30:00")

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

    def test_snapshot_restores_a_pending_published_card_with_corrected_kickoff(self) -> None:
        ledger = self._ledger()
        ledger.loc[0, "date"] = "2026-08-29 15:30:00"
        ledger.loc[0, "predicted_probability"] = 0.43
        snapshot = {
            "meta": {"activePortfolio": DEFAULT_PORTFOLIO_NAME},
            "summary": {"upcomingBets": 0},
            "tracking": {},
            "performance": {"live": {}},
            "predictions": [],
            "activity": [
                {
                    "date": "2026-08-29T07:30:00+02:00",
                    "league": "EPL",
                    "homeTeam": "Ipswich",
                    "awayTeam": "Sunderland",
                    "status": "pending_data_refresh",
                }
            ],
        }

        patched = update_public_snapshot(
            snapshot,
            ledger,
            portfolio_name=DEFAULT_PORTFOLIO_NAME,
            generated_at=datetime(2026, 8, 29, 11, 15, tzinfo=timezone.utc),
        )

        self.assertEqual(len(patched["predictions"]), 1)
        self.assertEqual(patched["predictions"][0]["date"], "2026-08-29 15:30:00")
        self.assertEqual(patched["predictions"][0]["adviceLabel"], "Pari déjà publié")
        self.assertEqual(patched["activity"][0]["date"], "2026-08-29 15:30:00")


if __name__ == "__main__":
    unittest.main()
