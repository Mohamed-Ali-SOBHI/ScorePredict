from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from inference.evaluate_live_portfolio import build_summary, evaluate_rows, prepare_ledger
from inference.live_tracking import (
    TRACKING_COLUMNS,
    append_tracking_rows,
    build_tracking_rows,
    canonicalize_tracking_rows,
)
from inference.portfolio_presets import (
    DEFAULT_PORTFOLIO_NAME,
    PORTFOLIO_PRESETS,
    PRODUCTION_PORTFOLIO_NAME,
    SHADOW_PORTFOLIO_NAMES,
)
from inference.predict_upcoming_portfolio import (
    ALL_EXPORT_COLUMNS,
    BET_EXPORT_COLUMNS,
    ensure_tracking_ledger,
    keep_fixtures_before_kickoff,
    write_exports,
)
from inference.track_published_predictions import published_rows


class PredictionTrackingTests(unittest.TestCase):
    def test_published_trend_uses_most_likely_outcome_and_matching_odds(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "date": "2026-08-15 19:30:00",
                    "league": "La_liga",
                    "team_name": "Alaves",
                    "opponent_name": "Getafe",
                    "recommended_bet": False,
                    "selected_outcome": "draw",
                    "selected_odds": 3.0,
                    "pred_home_win": 0.51,
                    "pred_draw": 0.29,
                    "pred_away_win": 0.20,
                    "market_home_win_odds_open": 2.1,
                    "market_draw_odds_open": 3.0,
                    "market_away_win_odds_open": 3.8,
                    "strategy_name": "example",
                }
            ]
        )
        row = published_rows(source).iloc[0]
        self.assertEqual(row["selected_outcome"], "home_win")
        self.assertEqual(row["selected_odds"], 2.1)
        self.assertFalse(row["recommended_bet"])

    def test_published_recommendation_accepts_outcome_text(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "date": "2026-08-30 17:30:00",
                    "league": "Bundesliga",
                    "team_name": "Augsburg",
                    "opponent_name": "Schalke 04",
                    "recommended_bet": "draw",
                    "selected_outcome": "draw",
                    "selected_odds": 3.9,
                    "strategy_name": "bundesliga_draw",
                }
            ]
        )
        row = published_rows(source).iloc[0]
        self.assertTrue(row["recommended_bet"])
        self.assertEqual(row["selected_outcome"], "draw")

    def test_future_prediction_stays_pending_when_latest_result_is_older(self) -> None:
        ledger = pd.DataFrame(
            [
                {
                    "league": "La_liga",
                    "match_date": pd.Timestamp("2026-08-15"),
                    "home_team_norm": "alaves",
                    "away_team_norm": "getafe",
                    "selected_outcome": "home_win",
                    "selected_odds": 2.1,
                    "stake_eur": 1.0,
                }
            ]
        )
        results = pd.DataFrame(
            [
                {
                    "league": "La_liga",
                    "match_date": pd.Timestamp("2026-05-24"),
                    "home_team_norm": "real madrid",
                    "away_team_norm": "barcelona",
                    "actual_outcome": "draw",
                }
            ]
        )
        evaluated = evaluate_rows(ledger, results, as_of_date=pd.Timestamp("2026-08-11"))
        self.assertEqual(evaluated.iloc[0]["result_status"], "pending")

    def test_same_day_prediction_stays_pending_before_kickoff(self) -> None:
        ledger = pd.DataFrame(
            [
                {
                    "date": "2026-08-22 16:00:00",
                    "league": "EPL",
                    "team_name": "Ipswich",
                    "opponent_name": "Sunderland",
                    "selected_outcome": "draw",
                    "selected_odds": 3.5,
                    "portfolio_name": PRODUCTION_PORTFOLIO_NAME,
                    "recommended": True,
                }
            ]
        )
        results = pd.DataFrame(
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
            results,
            as_of_date=pd.Timestamp("2026-08-22 14:30:00"),
        )

        self.assertEqual(evaluated.iloc[0]["result_status"], "pending")

    def test_finished_match_records_the_real_score_and_result(self) -> None:
        ledger = pd.DataFrame(
            [
                {
                    "league": "EPL",
                    "match_date": pd.Timestamp("2026-08-22"),
                    "home_team_norm": "ipswich",
                    "away_team_norm": "sunderland",
                    "selected_outcome": "draw",
                    "selected_odds": 3.5,
                    "stake_eur": 2.5,
                }
            ]
        )
        results = pd.DataFrame(
            [
                {
                    "league": "EPL",
                    "match_date": pd.Timestamp("2026-08-22"),
                    "home_team_norm": "ipswich",
                    "away_team_norm": "sunderland",
                    "actual_outcome": "draw",
                    "actual_home_score": 1,
                    "actual_away_score": 1,
                }
            ]
        )

        evaluated = evaluate_rows(ledger, results, as_of_date=pd.Timestamp("2026-08-23"))

        self.assertEqual(evaluated.iloc[0]["result_status"], "won")
        self.assertEqual(evaluated.iloc[0]["actual_home_score"], 1)
        self.assertEqual(evaluated.iloc[0]["actual_away_score"], 1)

    def test_first_published_prediction_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.csv"
            first = pd.DataFrame([{"snapshot_key": "fixture", "selected_odds": 2.1, "result_status": "pending"}])
            second = pd.DataFrame([{"snapshot_key": "fixture", "selected_odds": 2.5, "result_status": "pending"}])
            append_tracking_rows(first, ledger)
            append_tracking_rows(second, ledger)
            saved = pd.read_csv(ledger)
            self.assertEqual(saved.iloc[0]["selected_odds"], 2.1)

    def test_tracking_key_is_isolated_by_portfolio(self) -> None:
        bet = pd.DataFrame(
            [
                {
                    "date": "2026-08-15 15:00:00",
                    "league": "EPL",
                    "team_name": "Arsenal",
                    "opponent_name": "Liverpool",
                    "selected_outcome": "draw",
                    "selected_odds": 4.0,
                    "recommended_bet": "draw",
                }
            ]
        )
        first = build_tracking_rows(bet, portfolio_name="portfolio_a")
        second = build_tracking_rows(bet, portfolio_name="portfolio_b")
        self.assertNotEqual(first.iloc[0]["snapshot_key"], second.iloc[0]["snapshot_key"])
        self.assertTrue(first.iloc[0]["recommended"])

    def test_tracking_key_ignores_kickoff_time_changes(self) -> None:
        rows = pd.DataFrame(
            [
                {
                    "prediction_generated_at_utc": "2026-08-20T06:00:00Z",
                    "portfolio_name": PRODUCTION_PORTFOLIO_NAME,
                    "date": "2026-08-22 07:00:00",
                    "league": "EPL",
                    "team_name": "Ipswich",
                    "opponent_name": "Sunderland",
                    "selected_outcome": "draw",
                    "snapshot_key": "old-1",
                    "result_status": "pending",
                },
                {
                    "prediction_generated_at_utc": "2026-08-21T06:00:00Z",
                    "portfolio_name": PRODUCTION_PORTFOLIO_NAME,
                    "date": "2026-08-22 10:00:00",
                    "league": "EPL",
                    "team_name": "Ipswich Town",
                    "opponent_name": "Sunderland",
                    "selected_outcome": "draw",
                    "snapshot_key": "old-2",
                    "result_status": "won",
                    "actual_home_score": 1,
                    "actual_away_score": 1,
                },
            ]
        )

        canonical = canonicalize_tracking_rows(rows)

        self.assertEqual(len(canonical), 1)
        self.assertIn("|2026-08-22|EPL|ipswich|sunderland|draw", canonical.iloc[0]["snapshot_key"])
        self.assertEqual(canonical.iloc[0]["result_status"], "won")

    def test_live_summary_counts_a_rescheduled_match_once(self) -> None:
        evaluated = pd.DataFrame(
            [
                {
                    "portfolio_name": PRODUCTION_PORTFOLIO_NAME,
                    "league": "EPL",
                    "match_date": pd.Timestamp("2026-08-22"),
                    "home_team_norm": "ipswich",
                    "away_team_norm": "sunderland",
                    "selected_outcome": "draw",
                    "result_status": "pending",
                },
                {
                    "portfolio_name": PRODUCTION_PORTFOLIO_NAME,
                    "league": "EPL",
                    "match_date": pd.Timestamp("2026-08-22"),
                    "home_team_norm": "ipswich",
                    "away_team_norm": "sunderland",
                    "selected_outcome": "draw",
                    "result_status": "pending",
                },
            ]
        )

        summary = build_summary(
            evaluated,
            freeze_date="2026-08-12",
            as_of_date="2026-08-21",
            portfolio_name=PRODUCTION_PORTFOLIO_NAME,
        )

        self.assertEqual(summary["published_predictions"], 1)
        self.assertEqual(summary["pending_bets"], 1)

    def test_live_evaluation_keeps_only_active_recommended_bets(self) -> None:
        ledger = pd.DataFrame(
            [
                {
                    "date": "2026-08-15 15:00:00",
                    "league": "EPL",
                    "team_name": "Arsenal",
                    "opponent_name": "Liverpool",
                    "selected_outcome": "draw",
                    "selected_odds": 4.0,
                    "portfolio_name": PRODUCTION_PORTFOLIO_NAME,
                    "recommended": True,
                },
                {
                    "date": "2026-08-15 17:00:00",
                    "league": "EPL",
                    "team_name": "Chelsea",
                    "opponent_name": "Everton",
                    "selected_outcome": "home_win",
                    "selected_odds": 2.0,
                    "portfolio_name": PRODUCTION_PORTFOLIO_NAME,
                    "recommended": False,
                },
                {
                    "date": "2026-08-16 15:00:00",
                    "league": "EPL",
                    "team_name": "Fulham",
                    "opponent_name": "Leeds",
                    "selected_outcome": "draw",
                    "selected_odds": 3.5,
                    "portfolio_name": "legacy_portfolio",
                    "recommended": True,
                },
            ]
        )
        prepared = prepare_ledger(
            ledger,
            pd.Timestamp("2026-08-12"),
            portfolio_name=PRODUCTION_PORTFOLIO_NAME,
        )
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared.iloc[0]["team_name"], "Arsenal")

    def test_live_evaluation_accepts_mixed_supabase_utc_and_naive_dates(self) -> None:
        ledger = pd.DataFrame(
            [
                {
                    "date": "2026-08-30T11:30:00+00:00",
                    "league": "Bundesliga",
                    "team_name": "Augsburg",
                    "opponent_name": "Schalke 04",
                    "selected_outcome": "draw",
                    "selected_odds": 3.9,
                    "portfolio_name": PRODUCTION_PORTFOLIO_NAME,
                    "recommended": True,
                },
                {
                    "date": "2026-08-31 15:00:00",
                    "league": "Bundesliga",
                    "team_name": "Freiburg",
                    "opponent_name": "Werder Bremen",
                    "selected_outcome": "draw",
                    "selected_odds": 3.75,
                    "portfolio_name": PRODUCTION_PORTFOLIO_NAME,
                    "recommended": True,
                },
            ]
        )
        prepared = prepare_ledger(
            ledger,
            pd.Timestamp("2026-08-12"),
            portfolio_name=PRODUCTION_PORTFOLIO_NAME,
        )
        self.assertEqual(len(prepared), 2)
        self.assertEqual(
            prepared["date"].tolist(),
            [pd.Timestamp("2026-08-30 13:30:00"), pd.Timestamp("2026-08-31 15:00:00")],
        )
        self.assertIsNone(prepared["date"].dt.tz)

    def test_default_portfolio_is_the_versioned_champion(self) -> None:
        self.assertEqual(DEFAULT_PORTFOLIO_NAME, PRODUCTION_PORTFOLIO_NAME)

    def test_shadow_portfolios_are_versioned_and_never_become_the_default(self) -> None:
        self.assertNotIn(DEFAULT_PORTFOLIO_NAME, SHADOW_PORTFOLIO_NAMES)
        self.assertEqual(len(SHADOW_PORTFOLIO_NAMES), 2)
        for portfolio_name in SHADOW_PORTFOLIO_NAMES:
            self.assertIn(portfolio_name, PORTFOLIO_PRESETS)
            self.assertTrue(portfolio_name.startswith("shadow_"))

    def test_prediction_run_rejects_fixtures_after_kickoff(self) -> None:
        fixtures = pd.DataFrame(
            {
                "date": [
                    "2026-09-01 14:00:00",
                    "2026-09-01 16:00:00",
                ]
            }
        )
        remaining = keep_fixtures_before_kickoff(fixtures, "2026-09-01 15:00:00")
        self.assertEqual(remaining["date"].tolist(), ["2026-09-01 16:00:00"])

    def test_empty_active_portfolio_keeps_ledger_schema(self) -> None:
        ledger = pd.DataFrame(
            [
                {
                    "date": "2026-08-15 15:00:00",
                    "league": "EPL",
                    "team_name": "Arsenal",
                    "opponent_name": "Liverpool",
                    "selected_outcome": "draw",
                    "selected_odds": 4.0,
                    "portfolio_name": "legacy_portfolio",
                    "recommended": True,
                }
            ]
        )
        prepared = prepare_ledger(
            ledger,
            pd.Timestamp("2026-08-12"),
            portfolio_name=PRODUCTION_PORTFOLIO_NAME,
        )
        self.assertTrue(prepared.empty)
        self.assertIn("league", prepared.columns)

    def test_empty_prediction_run_replaces_exports_with_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_all = Path(tmp) / "all.csv"
            output_bets = Path(tmp) / "bets.csv"
            write_exports(pd.DataFrame(), pd.DataFrame(), output_all=output_all, output_bets=output_bets)
            self.assertEqual(list(pd.read_csv(output_all).columns), ALL_EXPORT_COLUMNS)
            self.assertEqual(list(pd.read_csv(output_bets).columns), BET_EXPORT_COLUMNS)

    def test_empty_shadow_run_still_creates_a_ledger_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "shadow" / "ledger.csv"
            ensure_tracking_ledger(ledger)
            self.assertTrue(ledger.exists())
            self.assertIn("portfolio_name", pd.read_csv(ledger).columns)

    def test_header_only_shadow_ledger_is_a_valid_empty_evaluation(self) -> None:
        prepared = prepare_ledger(
            pd.DataFrame(columns=TRACKING_COLUMNS),
            pd.Timestamp("2026-09-01"),
            portfolio_name=SHADOW_PORTFOLIO_NAMES[0],
        )
        self.assertTrue(prepared.empty)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(prepared["date"]))
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(prepared["match_date"]))


if __name__ == "__main__":
    unittest.main()
