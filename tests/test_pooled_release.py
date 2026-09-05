from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import pandas as pd

from inference.portfolio_presets import (DEFAULT_PORTFOLIO_NAME, LEGACY_PRODUCTION_PORTFOLIO_NAME,
    PORTFOLIO_PRESETS, PRODUCTION_POOLED_STRATEGIES, PRODUCTION_RELEASE_PATH)
from inference.pooled_release import validate_release, load_release_models
from inference.result_monitor import update_public_snapshot
from inference.supabase_prediction_store import pull
from inference.result_monitor import main as monitor_main
from tests import test_result_monitor as monitor_fixture


class PooledReleaseTests(unittest.TestCase):
    def test_new_policy_is_separate_and_uses_one_unweighted_gate(self):
        self.assertNotEqual(DEFAULT_PORTFOLIO_NAME, LEGACY_PRODUCTION_PORTFOLIO_NAME)
        self.assertIn(LEGACY_PRODUCTION_PORTFOLIO_NAME, PORTFOLIO_PRESETS)
        self.assertEqual(len(PRODUCTION_POOLED_STRATEGIES), 4)
        self.assertEqual({s.training_weight_mode for s in PRODUCTION_POOLED_STRATEGIES}, {"unweighted"})
        self.assertEqual({(s.threshold, s.edge_min) for s in PRODUCTION_POOLED_STRATEGIES}, {(.1, .04)})

    def test_checked_in_models_and_benchmark_are_sealed(self):
        manifest = validate_release()
        self.assertEqual((manifest["train_max_season"], manifest["filter_validation_season"], manifest["live_season"]), (2024, 2025, 2026))
        report = json.loads((PRODUCTION_RELEASE_PATH / "benchmark.json").read_text(encoding="utf-8"))
        self.assertEqual(report["metrics"]["bet_count"], 63)
        self.assertAlmostEqual(report["metrics"]["roi"], .5068253968253968)
        self.assertEqual(report["scope"]["training_max_season"], 2023)

    def test_no_silent_retrain_or_threshold_change(self):
        with self.assertRaisesRegex(ValueError, "sealed"):
            load_release_models(PRODUCTION_POOLED_STRATEGIES, train_max_season=2024, force_retrain=True)
        with self.assertRaisesRegex(ValueError, "Training season"):
            load_release_models(PRODUCTION_POOLED_STRATEGIES, train_max_season=2025)
        altered = [replace(s, threshold=0) for s in PRODUCTION_POOLED_STRATEGIES]
        with self.assertRaisesRegex(ValueError, "filters differ"):
            load_release_models(altered, train_max_season=2024)

    def test_monitor_does_not_mix_two_portfolio_versions(self):
        with self.assertRaisesRegex(ValueError, "another portfolio"):
            update_public_snapshot({"meta": {"activePortfolio": LEGACY_PRODUCTION_PORTFOLIO_NAME}},
                pd.DataFrame(), portfolio_name=DEFAULT_PORTFOLIO_NAME, generated_at=datetime.now(timezone.utc))

    def test_pulling_new_portfolio_preserves_retired_local_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.csv"
            pd.DataFrame([{"portfolio_name": LEGACY_PRODUCTION_PORTFOLIO_NAME,
                           "snapshot_key": "old-result", "result_status": "lost"}]).to_csv(ledger, index=False)
            response = Mock()
            response.json.return_value = []
            with patch("inference.supabase_prediction_store.configuration", return_value=("https://example.test", "fake")), \
                 patch("inference.supabase_prediction_store.requests.get", return_value=response):
                pull(ledger, Path(tmp) / "status.json", portfolio_name=DEFAULT_PORTFOLIO_NAME)
            saved = pd.read_csv(ledger)
            self.assertEqual(saved.snapshot_key.tolist(), ["old-result"])
            self.assertEqual(saved.result_status.tolist(), ["lost"])

    def test_retired_bets_are_settled_but_not_counted_in_new_roi(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = monitor_fixture.ResultMonitorTests._ledger()
            retired = current.assign(portfolio_name=LEGACY_PRODUCTION_PORTFOLIO_NAME, snapshot_key="retired-bet")
            ledger = root / "ledger.csv"
            pd.concat([current, retired], ignore_index=True).to_csv(ledger, index=False)
            snapshot = root / "dashboard.json"
            snapshot.write_text(json.dumps({"meta": {"activePortfolio": DEFAULT_PORTFOLIO_NAME}}), encoding="utf-8")
            argv = ["result_monitor", "--ledger", str(ledger), "--snapshot", str(snapshot),
                    "--status-output", str(root / "status.json"), "--include-retired", "--as-of", "2026-08-22 19:00:00"]
            with patch("sys.argv", argv), patch("inference.result_monitor.collect_results_for_due_rows",
                    return_value=(monitor_fixture.ResultMonitorTests._official("FT"), [])):
                monitor_main()
            self.assertEqual(pd.read_csv(ledger).result_status.tolist(), ["won", "won"])
            public = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual(public["summary"]["wonPredictions"], 1)
            self.assertEqual(len(public["activity"]), 1)


if __name__ == "__main__":
    unittest.main()
