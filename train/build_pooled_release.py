"""Build the user-approved pooled policy once; never run training inside daily CI."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from inference.portfolio_presets import PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026
from inference.upcoming_portfolio_strategy import train_frozen_models, score_strategy_rows
from train.research_challengers_v2 import file_hash, fit_betting_policy, save_json, summarize_bets

RELEASE = ROOT / "inference/releases/draw_pooled_2026_09_05"
RESEARCH = ROOT / "train/output/research_v2_native_2026_09_05"
PORTFOLIO = "production_draw_pooled_unweighted_2026_09_05"


def main():
    if (RELEASE / "manifest.json").exists():
        raise SystemExit("Release already sealed; use a new version instead of overwriting it")
    RELEASE.mkdir(parents=True, exist_ok=True)
    dataset_path = RESEARCH / "dataset_2014_2025.csv.gz"
    dataset = pd.read_csv(dataset_path, parse_dates=["date"])
    strategies = [replace(s, training_weight_mode="unweighted") for s in PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026]
    bundles = train_frozen_models(dataset, strategies, train_max_season=2024)
    validation = dataset[dataset.season == 2025].copy()
    scored = score_strategy_rows(validation, bundles, strategies)
    frame = scored.drop_duplicates("match_id").copy()
    frame["p_away"] = frame.pred_away_win
    frame["p_home"] = frame.pred_home_win
    frame["p_draw"] = frame.multiclass_draw_probability
    frame["p_binary_draw"] = frame.binary_draw_probability
    settings = fit_betting_policy(frame, "pooled_cautious")
    if not settings:
        raise SystemExit("No pooled filter qualifies on 2025 validation; no production release generated")
    by_name = {s["strategy"]: s for s in settings}
    entries = []
    for strategy in strategies:
        decision = by_name[strategy.name]
        live = replace(strategy, threshold=decision["threshold"], edge_min=decision["edge_min"])
        bundle = bundles[strategy.name]
        models = {}
        for label, model, cols in (("primary", bundle.model, bundle.feature_cols),
                                    ("secondary", bundle.secondary_model, bundle.secondary_feature_cols)):
            path = RELEASE / f"{strategy.name}_{label}.ubj"
            model.save_model(path)
            # Reload and verify inference with a different thread count. No refit.
            from xgboost import XGBClassifier
            restored = XGBClassifier(n_jobs=1)
            restored.load_model(path)
            probe = validation[validation.league == strategy.bet_league].iloc[:100]
            np.testing.assert_allclose(model.predict_proba(probe[cols]), restored.predict_proba(probe[cols]), rtol=0, atol=1e-7)
            models[label] = {"file": path.name, "sha256": file_hash(path), "features": cols}
        entries.append({"strategy": asdict(live), "models": models})

    benchmark = json.loads((RESEARCH / "report.json").read_text(encoding="utf-8"))["portfolio_results"]["unweighted__pooled_cautious"]["season_2025"]
    bets = pd.read_csv(RESEARCH / "all_test_bets.csv.gz", parse_dates=["date"])
    bets = bets[(bets.portfolio == "unweighted__pooled_cautious") & (bets.season == 2025)].copy()
    bets["profit"] = np.where(bets.target == 1, bets.selected_odds-1, -1)
    bets.to_csv(RELEASE / "benchmark_bets.csv", index=False)
    benchmark_report = {
        "portfolio_name": PORTFOLIO, "selection_mode": "exploratory_pooled_policy_walk_forward",
        "strategy_count": 4, "scope": {"label": "Simulation exploratoire 2025/26 — pas le suivi réel",
            "training_max_season": 2023, "validation_season": 2024, "test_season": 2025},
        "metrics": {"bet_count": benchmark["bets"], "total_profit": benchmark["profit_units"],
            "roi": benchmark["roi"], "roi_ci_low": benchmark["day_block_roi_interval_95pct"][0],
            "roi_ci_high": benchmark["day_block_roi_interval_95pct"][1], "hit_rate": benchmark["hit_rate"],
            "avg_odds": benchmark["average_odds"], "max_drawdown": benchmark["max_drawdown_units"],
            "start_date": bets.date.min().date().isoformat(), "end_date": bets.date.max().date().isoformat()},
        "clv_metrics": {"available": False},
        "verdict": {"evidence_level": "exploratoire, non validée sur de nouveaux matchs", "strengths": [],
            "risks": ["Choisi après comparaison de nombreuses variantes historiques.",
                      "Le rendement varie fortement entre entraînements.",
                      "La saison live utilise le même protocole avec une année supplémentaire de données, pas les modèles du backtest."]},
        "monthly_rows": [], "league_rows": [],
    }
    save_json(RELEASE / "benchmark.json", benchmark_report)
    manifest = {"portfolio_name": PORTFOLIO, "policy": "unweighted__pooled_cautious", "live_season": 2026,
                "train_max_season": 2024, "filter_validation_season": 2025,
                "activated_at_utc": datetime.now(timezone.utc).isoformat(),
                "dataset_sha256": file_hash(dataset_path), "source_sha256": file_hash(Path(__file__)),
                "calibration": settings, "entries": entries,
                "runtime": {"xgboost": "3.4.1", "training_threads": 20, "seed": 42},
                "benchmark_sha256": file_hash(RELEASE / "benchmark.json"),
                "benchmark_bets_sha256": file_hash(RELEASE / "benchmark_bets.csv"),
                "historical_result_is_not_live_performance": True,
                "auto_retraining_allowed": False}
    save_json(RELEASE / "manifest.json", manifest)
    print(json.dumps({"portfolio": PORTFOLIO, "calibration": settings, "size_bytes": sum(p.stat().st_size for p in RELEASE.iterdir())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
