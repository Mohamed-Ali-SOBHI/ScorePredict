from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import sklearn
import xgboost

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from inference.portfolio_presets import (  # noqa: E402
    PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026,
    LEGACY_PRODUCTION_PORTFOLIO_NAME as PRODUCTION_PORTFOLIO_NAME,
)
from train.evaluate_model_challengers import (  # noqa: E402
    fit_predict_fixed_holdout,
    model_configurations,
    select_portfolio_bets,
)


DEFAULT_REPORT = "train/output/production_final_four_benchmark.json"
DEFAULT_BETS = "train/output/production_final_four_benchmark_bets.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze the reproducible holdout benchmark for the four live portfolio rules."
    )
    parser.add_argument("--dataset", default="train/dataset_home.csv")
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--bets", default=DEFAULT_BETS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--validation-season", type=int, default=2024)
    parser.add_argument("--test-season", type=int, default=2025)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def maximum_drawdown(profits: np.ndarray) -> float:
    cumulative = np.cumsum(profits)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cumulative]))[1:]
    return float(np.min(cumulative - peak)) if len(cumulative) else 0.0


def longest_losing_streak(wins: np.ndarray) -> int:
    longest = 0
    current = 0
    for won in wins:
        if won:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def summarize_group(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"bets": 0, "profit": 0.0, "roi": None, "hit_rate": None}
    return {
        "bets": int(len(frame)),
        "profit": float(frame["profit"].sum()),
        "roi": float(frame["profit"].mean()),
        "hit_rate": float(frame["won_bet"].mean()),
    }


def bootstrap_roi(profits: np.ndarray) -> tuple[float, float, float]:
    rng = np.random.default_rng(20260901)
    values = profits[rng.integers(0, len(profits), size=(10000, len(profits)))].mean(axis=1)
    return (
        float(np.quantile(values, 0.025)),
        float(np.quantile(values, 0.975)),
        float(np.mean(values > 0.0)),
    )


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset)
    dataset = pd.read_csv(dataset_path)
    dataset["date"] = pd.to_datetime(dataset["date"])
    dataset["season"] = pd.to_numeric(dataset["season"], errors="coerce")
    dataset = dataset[dataset["target"].notna() & dataset["season"].notna()].copy()
    dataset["target"] = dataset["target"].astype(int)

    configurations, strategy_to_model = model_configurations()
    prediction_frames = []
    for model_id, strategy in configurations:
        frame, _ = fit_predict_fixed_holdout(
            dataset,
            strategy,
            "current",
            validation_season=args.validation_season,
            test_season=args.test_season,
            seed=args.seed,
        )
        frame["model_id"] = model_id
        prediction_frames.append(frame)
    predictions = pd.concat(prediction_frames, ignore_index=True)
    test_predictions = predictions[predictions["season"] == args.test_season].copy()
    bets = select_portfolio_bets(test_predictions, strategy_to_model, "current")

    identity_columns = ["match_id", "team_name", "opponent_name"]
    identity = dataset[identity_columns].drop_duplicates(subset=["match_id"])
    bets = bets.merge(identity, on="match_id", how="left", validate="many_to_one")
    bets["selected_outcome"] = "draw"
    bets["selected_odds"] = bets["market_draw_odds_open"].astype(float)
    bets["predicted_probability"] = np.minimum(
        bets["p_draw"].to_numpy(dtype=float),
        bets["p_binary_draw"].to_numpy(dtype=float),
    )
    bets["market_probability"] = bets["market_draw_prob_open"].astype(float)
    bets["edge"] = bets["predicted_probability"] - bets["market_probability"]
    bets["expected_value"] = bets["predicted_probability"] * bets["selected_odds"] - 1.0
    bets["won_bet"] = bets["target"].astype(int) == 1
    bets["profit"] = np.where(bets["won_bet"], bets["selected_odds"] - 1.0, -1.0)
    bets = bets.sort_values(["date", "match_id"]).reset_index(drop=True)

    profits = bets["profit"].to_numpy(dtype=float)
    wins = bets["won_bet"].to_numpy(dtype=bool)
    roi_low, roi_high, roi_positive = bootstrap_roi(profits)
    monthly_rows = []
    for month, part in bets.groupby(bets["date"].dt.to_period("M"), sort=True):
        monthly_rows.append({"month": str(month), **summarize_group(part)})
    league_rows = []
    for league, part in bets.groupby("league", sort=True):
        league_rows.append({"league": league, **summarize_group(part)})
    strategy_rows = []
    for strategy_name, part in bets.groupby("strategy_name", sort=True):
        strategy_rows.append({"strategy_name": strategy_name, **summarize_group(part)})

    report_path = Path(args.report)
    bets_path = Path(args.bets)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    bets_path.parent.mkdir(parents=True, exist_ok=True)
    export_columns = [
        "match_id",
        "date",
        "season",
        "league",
        "team_name",
        "opponent_name",
        "selected_outcome",
        "selected_odds",
        "predicted_probability",
        "market_probability",
        "edge",
        "expected_value",
        "target",
        "won_bet",
        "profit",
        "strategy_name",
    ]
    bets[export_columns].to_csv(bets_path, index=False)

    source_files = [
        Path("inference/portfolio_presets.py"),
        Path("inference/upcoming_portfolio_strategy.py"),
        Path("train/ml_common.py"),
        Path(__file__).relative_to(PROJECT_ROOT),
    ]
    report = {
        "portfolio_name": PRODUCTION_PORTFOLIO_NAME,
        "selection_mode": "four_final_rules_frozen_before_test",
        "strategy_count": len(PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026),
        "scope": {
            "label": "Test final 2025/26",
            "training_max_season": args.validation_season - 1,
            "validation_season": args.validation_season,
            "test_season": args.test_season,
        },
        "metrics": {
            "bet_count": int(len(bets)),
            "total_profit": float(profits.sum()),
            "roi": float(profits.mean()),
            "roi_ci_low": roi_low,
            "roi_ci_high": roi_high,
            "bootstrap_prob_roi_positive": roi_positive,
            "hit_rate": float(wins.mean()),
            "avg_odds": float(bets["selected_odds"].mean()),
            "avg_edge": float(bets["edge"].mean()),
            "avg_expected_value": float(bets["expected_value"].mean()),
            "max_drawdown": maximum_drawdown(profits),
            "longest_losing_streak": longest_losing_streak(wins),
            "start_date": bets["date"].min().date().isoformat(),
            "end_date": bets["date"].max().date().isoformat(),
        },
        "clv_metrics": {
            "available": False,
            "reason": "Closing odds are not present in the frozen production dataset.",
        },
        "verdict": {
            "evidence_level": "encourageante mais non concluante",
            "strengths": [
                "Les quatre règles évaluées sont exactement celles de la production.",
                "Les modèles et les règles ont été figés avant la saison de test.",
                "Aucun résultat 2025/26 n'a servi à l'entraînement ou au réglage.",
            ],
            "risks": [
                "L'intervalle du rendement traverse zéro.",
                "Une seule saison de test ne suffit pas à garantir un rendement futur.",
            ],
        },
        "monthly_rows": monthly_rows,
        "league_rows": league_rows,
        "strategy_rows": strategy_rows,
        "reproducibility": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "seed": args.seed,
            "dataset_path": dataset_path.as_posix(),
            "dataset_sha256": file_sha256(dataset_path),
            "dataset_size_bytes": dataset_path.stat().st_size,
            "bets_sha256": file_sha256(bets_path),
            "source_sha256": {
                path.as_posix(): file_sha256(PROJECT_ROOT / path) for path in source_files
            },
            "runtime": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "scikit_learn": sklearn.__version__,
                "xgboost": xgboost.__version__,
            },
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"benchmark bets={len(bets)} profit={profits.sum():.2f} roi={profits.mean():.4f} "
        f"report={report_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
