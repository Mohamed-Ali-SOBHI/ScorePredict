import unittest
from datetime import datetime

import pandas as pd

from inference.prediction_window import in_prediction_window
from inference.result_monitor import update_public_snapshot
from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME
from production.dashboard import DashboardService


class PredictionWindowTests(unittest.TestCase):
    def test_activity_keeps_all_unresolved_choices_beyond_history_limit(self):
        rows = [
            {"snapshot_key": str(i), "date": f"2026-09-12T{(i % 24):02d}:00:00+02:00",
             "team_name": f"Home {i}", "opponent_name": "Away", "selected_outcome": "draw",
             "recommended": True, "result_status": "pending"}
            for i in range(40)
        ]
        self.assertEqual(len(DashboardService._activity_view(rows)), 40)

    def test_paris_midnight_and_dst_use_calendar_days(self):
        now = datetime.fromisoformat("2026-10-24T22:30:00+00:00")  # Oct 25 in Paris, DST change
        self.assertTrue(in_prediction_window("2026-10-27T22:59:00Z", now))
        self.assertFalse(in_prediction_window("2026-10-27T23:00:00Z", now))
        self.assertFalse(in_prediction_window("2026-10-24T12:00:00Z", now))

    def test_result_refresh_keeps_one_pending_and_archives_four_later_bets(self):
        now = datetime.fromisoformat("2026-09-06T13:00:00+02:00")
        ledger = pd.DataFrame([
            {"snapshot_key": str(i), "portfolio_name": DEFAULT_PORTFOLIO_NAME,
             "date": f"2026-09-{day:02d}T17:30:00+02:00", "league": "Bundesliga",
             "team_name": f"Home {i}", "opponent_name": f"Away {i}",
             "selected_outcome": "draw", "selected_odds": 4.0,
             "predicted_probability": .37, "stake_eur": 2.5,
             "recommended": True, "result_status": "pending"}
            for i, day in enumerate([6, 11, 12, 12, 12])
        ])
        snapshot = {"meta": {"activePortfolio": DEFAULT_PORTFOLIO_NAME}, "predictions": []}
        refreshed = update_public_snapshot(snapshot, ledger, portfolio_name=DEFAULT_PORTFOLIO_NAME, generated_at=now)
        self.assertEqual(len(refreshed["predictions"]), 1)
        self.assertEqual(refreshed["tracking"]["pending"], 1)
        self.assertEqual(refreshed["tracking"]["pendingAll"], 5)
        self.assertEqual(len(refreshed["activity"]), 5)
