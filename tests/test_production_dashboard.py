from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from production.dashboard import DashboardService
from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    if path.name in {"upcoming_portfolio_bets.csv", "upcoming_portfolio_predictions.csv"}:
        rows = [{"portfolio_name": DEFAULT_PORTFOLIO_NAME, **row} for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class DashboardServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        now = datetime.now(timezone.utc)
        current_season = now.year if now.month >= 7 else now.year - 1
        write_json(
            self.root / "train/output/data_quality_audit.json",
            {
                "generated_at": now.isoformat(),
                "raw_data": {
                    "status": "ok",
                    "unique_matches": 25000,
                    "date_min": "2014-08-01",
                    "date_max": now.date().isoformat(),
                },
                "dataset": {
                    "status": "ok",
                    "rows": 24999,
                    "completed_rows": 24999,
                    "season_max": current_season,
                    "missing_opening_odds_rows": 0,
                    "feature_infinite_values_multiclass": 0,
                    "feature_count_multiclass": 51,
                    "market_probability_sum_min": 1,
                    "market_probability_sum_max": 1,
                },
                "protocol": {"status": "ok", "folds": ["a", "b"], "top_experiment": {"name": "draw"}},
            },
        )
        write_json(
            self.root
            / "inference/releases/draw_pooled_2026_09_05/benchmark.json",
            {
                "selection_mode": "val",
                "strategy_count": 2,
                "metrics": {
                    "bet_count": 200,
                    "total_profit": 20,
                    "roi": 0.1,
                    "roi_ci_low": -0.03,
                    "roi_ci_high": 0.24,
                    "bootstrap_prob_roi_positive": 0.82,
                    "hit_rate": 0.3,
                    "avg_odds": 4.2,
                    "avg_edge": 0.12,
                    "max_drawdown": -9,
                    "longest_losing_streak": 8,
                    "start_date": "2025-08-01",
                    "end_date": "2026-05-01",
                },
                "clv_metrics": {"positive_clv_rate": 0.58, "avg_clv_odds_diff": 0.03},
                "verdict": {"evidence_level": "encourageante", "strengths": [], "risks": ["IC large"]},
                "monthly_rows": [{"month": "2026-01", "roi": 0.1, "profit": 2, "bets": 20}],
                "league_rows": [{"league": "EPL", "roi": 0.1, "profit": 2, "bets": 20}],
            },
        )
        write_csv(
            self.root / "inference/releases/draw_pooled_2026_09_05/benchmark_bets.csv",
            [{"date": "2025-08-01", "profit": "-1"}, {"date": "2025-08-10", "profit": "3"}],
        )
        write_csv(
            self.root / "inference/output/upcoming_portfolio_bets.csv",
            [
                {
                    "date": (now + timedelta(days=2)).isoformat(),
                    "league": "EPL",
                    "team_name": "Arsenal",
                    "opponent_name": "Liverpool",
                    "selected_outcome": "draw",
                    "selected_odds": "4.2",
                    "predicted_probability": "0.32",
                    "raw_model_probability": "0.32",
                    "market_probability": "0.24",
                    "edge": "0.08",
                    "value_score": "0.34",
                    "expected_value": "0.34",
                    "stake_eur": "2.5",
                    "potential_profit_eur_if_win": "8",
                    "strategy_names": "epl_draw",
                    "probability_note": "raw",
                }
            ],
        )
        write_csv(
            self.root / "inference/output/upcoming_portfolio_predictions.csv",
            [{"date": (now + timedelta(days=2)).isoformat(), "league": "EPL"}],
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_builds_ready_dashboard_from_valid_exports(self) -> None:
        payload = DashboardService(self.root, ttl_seconds=0).get_dashboard()
        self.assertEqual(payload["meta"]["status"], "ready")
        self.assertEqual(payload["summary"]["upcomingBets"], 1)
        self.assertEqual(payload["predictions"][0]["homeTeam"], "Arsenal")
        self.assertEqual(payload["predictions"][0]["stakeEur"], 2.5)
        self.assertEqual(payload["predictions"][0]["strategy"], "epl_draw")
        self.assertEqual(payload["quality"]["criticalFailures"], 0)
        self.assertEqual(payload["performance"]["curve"][-1]["value"], 2)

    def test_serializes_match_time_in_the_paris_timezone(self) -> None:
        rows = _read_for_test(self.root / "inference/output/upcoming_portfolio_bets.csv")
        future_paris = (datetime.now(ZoneInfo("Europe/Paris")) + timedelta(days=2)).replace(
            hour=16,
            minute=0,
            second=0,
            microsecond=0,
        )
        rows[0]["date"] = future_paris.strftime("%Y-%m-%d %H:%M:%S")
        write_csv(self.root / "inference/output/upcoming_portfolio_bets.csv", rows)

        payload = DashboardService(self.root, ttl_seconds=0).get_dashboard()

        self.assertEqual(payload["predictions"][0]["date"], future_paris.isoformat())

    def test_does_not_publish_expired_prediction(self) -> None:
        rows = _read_for_test(self.root / "inference/output/upcoming_portfolio_bets.csv")
        rows[0]["date"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        write_csv(self.root / "inference/output/upcoming_portfolio_bets.csv", rows)
        payload = DashboardService(self.root, ttl_seconds=0).get_dashboard()
        self.assertEqual(payload["predictions"], [])
        self.assertEqual(payload["meta"]["status"], "ready")

    def test_retired_export_cannot_be_presented_as_the_new_strategy(self) -> None:
        path = self.root / "inference/output/upcoming_portfolio_bets.csv"
        rows = _read_for_test(path)
        rows[0]["portfolio_name"] = "retired_portfolio"
        write_csv(path, rows)
        payload = DashboardService(self.root, ttl_seconds=0).get_dashboard()
        self.assertEqual(payload["predictions"], [])
        self.assertEqual(payload["meta"]["status"], "blocked")

    def test_counts_only_recommended_predictions_as_upcoming_bets(self) -> None:
        existing_bet = _read_for_test(self.root / "inference/output/upcoming_portfolio_bets.csv")[0]
        common = {
            "date": existing_bet["date"],
            "league": "EPL",
            "pred_home_win": "0.35",
            "pred_draw": "0.40",
            "pred_away_win": "0.25",
            "market_home_win_odds_open": "2.4",
            "market_draw_odds_open": "3.4",
            "market_away_win_odds_open": "3.2",
            "selected_outcome": "draw",
            "selected_odds": "3.4",
            "predicted_probability": "0.40",
            "market_probability": "0.29",
            "edge": "0.11",
            "expected_value": "0.36",
            "probability_note": "raw",
        }
        write_csv(
            self.root / "inference/output/upcoming_portfolio_predictions.csv",
            [
                common
                | {
                    "team_name": "Arsenal",
                    "opponent_name": "Liverpool",
                    "recommended_bet": "draw",
                },
                common
                | {
                    "team_name": "Chelsea",
                    "opponent_name": "Everton",
                    "recommended_bet": "",
                },
            ],
        )
        payload = DashboardService(self.root, ttl_seconds=0).get_dashboard()
        self.assertEqual(payload["summary"]["scoredFixtures"], 2)
        self.assertEqual(payload["summary"]["upcomingBets"], 1)
        self.assertEqual(len(payload["predictions"]), 1)

    def test_zero_recommendations_is_ready_and_hides_scored_trends(self) -> None:
        bets_path = self.root / "inference/output/upcoming_portfolio_bets.csv"
        bets_path.write_text("date,league,team_name,opponent_name\n", encoding="utf-8")
        write_csv(
            self.root / "inference/output/upcoming_portfolio_predictions.csv",
            [
                {
                    "date": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
                    "league": "EPL",
                    "team_name": "Arsenal",
                    "opponent_name": "Liverpool",
                    "recommended_bet": "",
                }
            ],
        )
        payload = DashboardService(self.root, ttl_seconds=0).get_dashboard()
        self.assertEqual(payload["meta"]["status"], "ready")
        self.assertEqual(payload["summary"]["scoredFixtures"], 1)
        self.assertEqual(payload["summary"]["upcomingBets"], 0)
        self.assertEqual(payload["predictions"], [])

    def test_uses_static_snapshot_when_sources_are_absent(self) -> None:
        empty_root = self.root / "empty"
        write_json(empty_root / "production/static/data/dashboard.json", {"meta": {"status": "attention"}})
        payload = DashboardService(empty_root, ttl_seconds=0).get_dashboard()
        self.assertEqual(payload["meta"]["servingMode"], "snapshot")

    def test_activity_merges_time_changes_and_keeps_the_verified_result(self) -> None:
        rows = [
            {
                "snapshot_key": "first",
                "date": "2026-08-22T07:00:00",
                "league": "EPL",
                "team_name": "Ipswich",
                "opponent_name": "Sunderland",
                "selected_outcome": "draw",
                "result_status": "pending",
                "recommended": "true",
            },
            {
                "snapshot_key": "second",
                "date": "2026-08-22T10:00:00",
                "league": "EPL",
                "team_name": "Ipswich",
                "opponent_name": "Sunderland",
                "selected_outcome": "draw",
                "result_status": "won",
                "actual_home_score": "1",
                "actual_away_score": "1",
                "recommended": "true",
            },
        ]

        activity = DashboardService._activity_view(rows)

        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0]["status"], "won")
        self.assertEqual(activity[0]["actualScore"], "1 - 1")

    def test_keeps_a_card_for_each_published_bet_still_to_play(self) -> None:
        now = datetime.now(timezone.utc)
        write_json(
            self.root / "inference/output/live_portfolio_evaluation_summary.json",
            {"portfolio_name": DEFAULT_PORTFOLIO_NAME, "pending_bets": 2},
        )
        write_csv(
            self.root / "inference/output/live_portfolio_evaluation.csv",
            [
                {
                    "snapshot_key": "older-published-bet",
                    "portfolio_name": DEFAULT_PORTFOLIO_NAME,
                    "date": (now + timedelta(days=1)).isoformat(),
                    "league": "EPL",
                    "team_name": "Hull",
                    "opponent_name": "Manchester United",
                    "selected_outcome": "draw",
                    "selected_odds": "4.1",
                    "predicted_probability": "0.31",
                    "market_probability": "0.24",
                    "edge": "0.07",
                    "expected_value": "0.27",
                    "stake_eur": "2.5",
                    "result_status": "pending",
                    "recommended": "true",
                },
                {
                    "snapshot_key": "old-strategy-bet",
                    "portfolio_name": "retired_portfolio",
                    "date": (now + timedelta(days=1)).isoformat(),
                    "league": "EPL",
                    "team_name": "Chelsea",
                    "opponent_name": "Everton",
                    "selected_outcome": "draw",
                    "selected_odds": "3.6",
                    "predicted_probability": "0.35",
                    "stake_eur": "2.5",
                    "result_status": "pending",
                    "recommended": "true",
                },
            ],
        )

        payload = DashboardService(self.root, ttl_seconds=0).get_dashboard()

        self.assertEqual(payload["summary"]["currentRecommendations"], 1)
        self.assertEqual(payload["summary"]["upcomingBets"], 2)
        self.assertEqual([row["homeTeam"] for row in payload["predictions"]], ["Hull", "Arsenal"])
        self.assertFalse(payload["predictions"][0]["isCurrentRecommendation"])
        self.assertEqual(payload["predictions"][0]["adviceLabel"], "Pari déjà publié")


def _read_for_test(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
