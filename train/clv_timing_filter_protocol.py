from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from ml_common import get_feature_cols, load_dataset
from validation_metrics import summarize_bets


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_PATH = SCRIPT_DIR / "dataset_home.csv"
DEFAULT_BETS_PATH = (
    SCRIPT_DIR
    / "output"
    / "experimental_protocol_targeted_favorite_fix"
    / "best_strategy_bets.csv"
)
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output" / "clv_timing_filter_protocol"

OUTCOME_TO_OPEN_ODDS_COL = {
    "home_win": "market_home_win_odds_open",
    "draw": "market_draw_odds_open",
    "away_win": "market_away_win_odds_open",
}
OUTCOME_TO_CLOSE_ODDS_COL = {
    "home_win": "market_home_win_odds_close",
    "draw": "market_draw_odds_close",
    "away_win": "market_away_win_odds_close",
}
OUTCOME_TO_OPEN_PROB_COL = {
    "home_win": "market_home_prob_open",
    "draw": "market_draw_prob_open",
    "away_win": "market_away_prob_open",
}


@dataclass(frozen=True)
class Fold:
    val_season: int
    test_season: int

    @property
    def label(self) -> str:
        return f"val{self.val_season}_test{self.test_season}"


class ConstantProbabilityModel:
    def __init__(self, probability: float):
        self.probability = float(probability)

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        positive = np.full(len(x), self.probability, dtype=float)
        negative = 1.0 - positive
        return np.column_stack([negative, positive])


def resolve_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk-forward timing filter that predicts whether selected opening odds will beat closing odds."
    )
    parser.add_argument("--data", default=str(DEFAULT_DATA_PATH))
    parser.add_argument("--bets", default=str(DEFAULT_BETS_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--start-val-season", type=int, default=2021)
    parser.add_argument("--end-val-season", type=int, default=2024)
    parser.add_argument("--min-val-examples", type=int, default=80)
    parser.add_argument("--min-val-keep-rate", type=float, default=0.15)
    parser.add_argument("--thresholds", default="0.45,0.50,0.55,0.60,0.65,0.70,0.75")
    parser.add_argument("--min-clv-odds-diff", type=float, default=0.0)
    parser.add_argument("--include-algo-features", action="store_true")
    parser.add_argument("--n-iterations", type=int, default=160)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bootstrap-iterations", type=int, default=5000)
    return parser.parse_args()


def parse_thresholds(raw: str) -> list[float]:
    values = [float(value.strip()) for value in raw.split(",") if value.strip()]
    if not values:
        raise ValueError("--thresholds must contain at least one number")
    return sorted(values)


def build_folds(df: pd.DataFrame, start_val_season: int, end_val_season: int) -> list[Fold]:
    seasons = {int(value) for value in df["season"].dropna().unique()}
    folds = []
    for val_season in range(start_val_season, end_val_season + 1):
        test_season = val_season + 1
        if val_season in seasons and test_season in seasons:
            folds.append(Fold(val_season=val_season, test_season=test_season))
    if not folds:
        raise ValueError("No valid folds found")
    return folds


def required_market_columns(outcomes: set[str]) -> set[str]:
    columns: set[str] = set()
    for outcome in outcomes:
        columns.add(OUTCOME_TO_OPEN_ODDS_COL[outcome])
        columns.add(OUTCOME_TO_CLOSE_ODDS_COL[outcome])
        columns.add(OUTCOME_TO_OPEN_PROB_COL[outcome])
    return columns


def add_selected_clv_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["timing_open_odds"] = np.nan
    result["timing_close_odds"] = np.nan
    result["timing_open_probability"] = np.nan
    for outcome in sorted(result["selected_outcome"].dropna().unique()):
        if outcome not in OUTCOME_TO_OPEN_ODDS_COL:
            raise ValueError(f"Unsupported selected_outcome: {outcome!r}")
        mask = result["selected_outcome"] == outcome
        result.loc[mask, "timing_open_odds"] = pd.to_numeric(
            result.loc[mask, OUTCOME_TO_OPEN_ODDS_COL[outcome]],
            errors="coerce",
        )
        result.loc[mask, "timing_close_odds"] = pd.to_numeric(
            result.loc[mask, OUTCOME_TO_CLOSE_ODDS_COL[outcome]],
            errors="coerce",
        )
        result.loc[mask, "timing_open_probability"] = pd.to_numeric(
            result.loc[mask, OUTCOME_TO_OPEN_PROB_COL[outcome]],
            errors="coerce",
        )
    result["timing_clv_odds_diff"] = result["timing_open_odds"] - result["timing_close_odds"]
    result["timing_positive_clv"] = result["timing_clv_odds_diff"] > 0.0
    return result


def build_outcome_training_frame(
    df: pd.DataFrame,
    *,
    outcomes: set[str],
    feature_cols: list[str],
    min_clv_odds_diff: float,
) -> pd.DataFrame:
    frames = []
    base_cols = [
        "match_id",
        "date",
        "league",
        "season",
        *feature_cols,
    ]
    for outcome in sorted(outcomes):
        outcome_frame = df[base_cols].copy()
        outcome_frame["selected_outcome"] = outcome
        outcome_frame["timing_open_odds"] = pd.to_numeric(
            df[OUTCOME_TO_OPEN_ODDS_COL[outcome]],
            errors="coerce",
        )
        outcome_frame["timing_close_odds"] = pd.to_numeric(
            df[OUTCOME_TO_CLOSE_ODDS_COL[outcome]],
            errors="coerce",
        )
        outcome_frame["timing_open_probability"] = pd.to_numeric(
            df[OUTCOME_TO_OPEN_PROB_COL[outcome]],
            errors="coerce",
        )
        frames.append(outcome_frame)
    result = pd.concat(frames, ignore_index=True)
    result["timing_clv_odds_diff"] = result["timing_open_odds"] - result["timing_close_odds"]
    result["timing_positive_clv_target"] = (
        result["timing_clv_odds_diff"] > min_clv_odds_diff
    ).astype(int)
    result = result.dropna(subset=["timing_open_odds", "timing_close_odds", "timing_open_probability"])
    return result


def timing_feature_columns(base_feature_cols: list[str]) -> list[str]:
    return [
        *base_feature_cols,
        "timing_open_odds",
        "timing_open_probability",
    ]


def fit_timing_model(
    train_frame: pd.DataFrame,
    *,
    feature_cols: list[str],
    seed: int,
    n_iterations: int,
) -> object:
    y = train_frame["timing_positive_clv_target"].astype(int)
    if y.nunique() < 2:
        return ConstantProbabilityModel(float(y.mean()) if len(y) else 0.5)

    model = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            (
                "classifier",
                HistGradientBoostingClassifier(
                    max_iter=n_iterations,
                    learning_rate=0.045,
                    max_leaf_nodes=15,
                    l2_regularization=0.05,
                    random_state=seed,
                ),
            ),
        ]
    )
    model.fit(train_frame[feature_cols], y)
    return model


def score_timing(model: object, frame: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
    proba = model.predict_proba(frame[feature_cols])
    return np.asarray(proba[:, 1], dtype=float)


def choose_threshold(
    val_scored: pd.DataFrame,
    thresholds: list[float],
    *,
    min_val_examples: int,
    min_val_keep_rate: float,
) -> dict[str, Any]:
    base_count = len(val_scored)
    base_rate = float(val_scored["timing_positive_clv_target"].mean()) if base_count else None
    candidates = []
    for threshold in thresholds:
        kept = val_scored[val_scored["timing_positive_clv_probability"] >= threshold].copy()
        keep_rate = len(kept) / float(base_count) if base_count else 0.0
        if len(kept) < min_val_examples or keep_rate < min_val_keep_rate:
            continue
        candidates.append(
            {
                "threshold": threshold,
                "val_examples": int(len(kept)),
                "val_keep_rate": float(keep_rate),
                "val_positive_clv_rate": float(kept["timing_positive_clv_target"].mean()),
                "val_avg_clv_odds_diff": float(kept["timing_clv_odds_diff"].mean()),
                "val_base_positive_clv_rate": base_rate,
            }
        )
    if candidates:
        return sorted(
            candidates,
            key=lambda row: (
                row["val_positive_clv_rate"],
                row["val_avg_clv_odds_diff"],
                row["val_examples"],
            ),
            reverse=True,
        )[0]

    fallback_threshold = 0.5
    kept = val_scored[val_scored["timing_positive_clv_probability"] >= fallback_threshold].copy()
    return {
        "threshold": fallback_threshold,
        "val_examples": int(len(kept)),
        "val_keep_rate": float(len(kept) / float(base_count)) if base_count else 0.0,
        "val_positive_clv_rate": float(kept["timing_positive_clv_target"].mean()) if len(kept) else None,
        "val_avg_clv_odds_diff": float(kept["timing_clv_odds_diff"].mean()) if len(kept) else None,
        "val_base_positive_clv_rate": base_rate,
        "fallback": True,
    }


def metric_summary(bets: pd.DataFrame, *, args: argparse.Namespace) -> dict[str, Any]:
    metrics = summarize_bets(
        bets,
        iterations=args.bootstrap_iterations,
        confidence_level=0.95,
        seed=args.seed,
    )
    if bets.empty:
        metrics.update(
            {
                "positive_clv_rate": None,
                "avg_clv_odds_diff": None,
                "median_clv_odds_diff": None,
                "avg_timing_probability": None,
            }
        )
        return metrics
    metrics.update(
        {
            "positive_clv_rate": float(bets["timing_positive_clv"].mean()),
            "avg_clv_odds_diff": float(bets["timing_clv_odds_diff"].mean()),
            "median_clv_odds_diff": float(bets["timing_clv_odds_diff"].median()),
            "avg_timing_probability": float(bets["timing_positive_clv_probability"].mean()),
        }
    )
    return metrics


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_No rows._"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = []
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            elif value is None:
                values.append("")
            else:
                values.append(str(value))
        body.append("| " + " | ".join(values) + " |")
    return "\n".join([header, sep, *body])


def write_report(
    output_path: Path,
    *,
    fold_rows: list[dict[str, Any]],
    base_metrics: dict[str, Any],
    filtered_metrics: dict[str, Any],
    args: argparse.Namespace,
    feature_count: int,
) -> None:
    lines = [
        "# CLV timing filter protocol",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Protocol",
        "",
        "- The timing model is trained only on seasons before the validation season.",
        "- Threshold selection uses the validation season only.",
        "- The following test season is filtered without using its results.",
        "- Target: opening selected odds greater than closing selected odds.",
        f"- Base feature count: `{feature_count}`",
        f"- Include algo features: `{args.include_algo_features}`",
        f"- Min CLV odds diff target: `{args.min_clv_odds_diff}`",
        "",
        "## Aggregate",
        "",
        markdown_table(
            [
                {
                    "portfolio": "base",
                    "bets": base_metrics["bet_count"],
                    "profit": base_metrics["total_profit"],
                    "roi": base_metrics["roi"],
                    "prob_roi_positive": base_metrics["bootstrap_prob_roi_positive"],
                    "positive_clv_rate": base_metrics["positive_clv_rate"],
                    "avg_clv_odds_diff": base_metrics["avg_clv_odds_diff"],
                },
                {
                    "portfolio": "timing_filtered",
                    "bets": filtered_metrics["bet_count"],
                    "profit": filtered_metrics["total_profit"],
                    "roi": filtered_metrics["roi"],
                    "prob_roi_positive": filtered_metrics["bootstrap_prob_roi_positive"],
                    "positive_clv_rate": filtered_metrics["positive_clv_rate"],
                    "avg_clv_odds_diff": filtered_metrics["avg_clv_odds_diff"],
                },
            ],
            [
                "portfolio",
                "bets",
                "profit",
                "roi",
                "prob_roi_positive",
                "positive_clv_rate",
                "avg_clv_odds_diff",
            ],
        ),
        "",
        "## Folds",
        "",
        markdown_table(
            fold_rows,
            [
                "fold",
                "threshold",
                "base_bets",
                "base_roi",
                "base_positive_clv_rate",
                "filtered_bets",
                "filtered_roi",
                "filtered_positive_clv_rate",
                "filtered_profit",
            ],
        ),
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    data_path = resolve_path(args.data)
    bets_path = resolve_path(args.bets)
    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_dataset(str(data_path)).dropna(subset=["target"]).copy()
    bets = pd.read_csv(bets_path)
    bets["date"] = pd.to_datetime(bets["date"])

    outcomes = {str(value) for value in bets["selected_outcome"].dropna().unique()}
    unsupported = outcomes - set(OUTCOME_TO_OPEN_ODDS_COL)
    if unsupported:
        raise ValueError(f"Unsupported outcomes in bets file: {sorted(unsupported)}")

    missing_market = sorted(required_market_columns(outcomes) - set(df.columns))
    if missing_market:
        raise ValueError(
            "Dataset is missing closing/opening market columns. Regenerate it with "
            f"--include-closing-market-data. Missing: {missing_market}"
        )

    base_feature_cols = get_feature_cols(
        df,
        include_draw_features=("draw" in outcomes),
        include_algo_features=args.include_algo_features,
    )
    model_feature_cols = timing_feature_columns(base_feature_cols)
    training_frame = build_outcome_training_frame(
        df,
        outcomes=outcomes,
        feature_cols=base_feature_cols,
        min_clv_odds_diff=args.min_clv_odds_diff,
    )

    missing_feature_cols = [column for column in base_feature_cols if column not in bets.columns]
    merge_cols = [
        "match_id",
        *[OUTCOME_TO_CLOSE_ODDS_COL[outcome] for outcome in sorted(outcomes)],
        *missing_feature_cols,
    ]
    merge_cols = list(dict.fromkeys(merge_cols))
    bets = bets.merge(df[merge_cols].drop_duplicates("match_id"), on="match_id", how="left", validate="many_to_one")
    bets = add_selected_clv_columns(bets)
    folds = build_folds(df, args.start_val_season, args.end_val_season)
    thresholds = parse_thresholds(args.thresholds)

    fold_rows: list[dict[str, Any]] = []
    filtered_frames = []
    scored_frames = []
    for fold in folds:
        train_frame = training_frame[training_frame["season"] < fold.val_season].copy()
        val_frame = training_frame[training_frame["season"] == fold.val_season].copy()
        test_bets = bets[bets["test_season"] == fold.test_season].copy()
        if train_frame.empty or val_frame.empty or test_bets.empty:
            continue

        model = fit_timing_model(
            train_frame,
            feature_cols=model_feature_cols,
            seed=args.seed + fold.val_season,
            n_iterations=args.n_iterations,
        )
        val_frame["timing_positive_clv_probability"] = score_timing(model, val_frame, model_feature_cols)
        threshold_row = choose_threshold(
            val_frame,
            thresholds,
            min_val_examples=args.min_val_examples,
            min_val_keep_rate=args.min_val_keep_rate,
        )

        test_bets["timing_positive_clv_probability"] = score_timing(model, test_bets, model_feature_cols)
        test_bets["timing_threshold"] = threshold_row["threshold"]
        test_bets["timing_filter_pass"] = (
            test_bets["timing_positive_clv_probability"] >= threshold_row["threshold"]
        )
        filtered = test_bets[test_bets["timing_filter_pass"]].copy()

        base_fold_metrics = metric_summary(test_bets, args=args)
        filtered_fold_metrics = metric_summary(filtered, args=args)
        fold_rows.append(
            {
                "fold": fold.label,
                "threshold": threshold_row["threshold"],
                "val_examples": threshold_row["val_examples"],
                "val_positive_clv_rate": threshold_row["val_positive_clv_rate"],
                "base_bets": base_fold_metrics["bet_count"],
                "base_profit": base_fold_metrics["total_profit"],
                "base_roi": base_fold_metrics["roi"],
                "base_positive_clv_rate": base_fold_metrics["positive_clv_rate"],
                "filtered_bets": filtered_fold_metrics["bet_count"],
                "filtered_profit": filtered_fold_metrics["total_profit"],
                "filtered_roi": filtered_fold_metrics["roi"],
                "filtered_positive_clv_rate": filtered_fold_metrics["positive_clv_rate"],
            }
        )
        scored_frames.append(test_bets)
        filtered_frames.append(filtered)
        print(fold_rows[-1])

    if not scored_frames:
        raise ValueError("No scored folds produced")

    scored_bets = pd.concat(scored_frames, ignore_index=True)
    filtered_bets = pd.concat(filtered_frames, ignore_index=True) if filtered_frames else pd.DataFrame()
    base_metrics = metric_summary(scored_bets, args=args)
    filtered_metrics = metric_summary(filtered_bets, args=args)

    scored_bets.to_csv(output_dir / "scored_bets.csv", index=False)
    filtered_bets.to_csv(output_dir / "filtered_bets.csv", index=False)
    pd.DataFrame(fold_rows).to_csv(output_dir / "fold_metrics.csv", index=False)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_path": str(data_path),
        "bets_path": str(bets_path),
        "feature_count": len(base_feature_cols),
        "model_feature_count": len(model_feature_cols),
        "outcomes": sorted(outcomes),
        "base_metrics": base_metrics,
        "filtered_metrics": filtered_metrics,
        "folds": fold_rows,
    }
    (output_dir / "clv_timing_filter_report.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    write_report(
        output_dir / "clv_timing_filter_report.md",
        fold_rows=fold_rows,
        base_metrics=base_metrics,
        filtered_metrics=filtered_metrics,
        args=args,
        feature_count=len(base_feature_cols),
    )
    print(
        {
            "base_bets": base_metrics["bet_count"],
            "base_roi": base_metrics["roi"],
            "base_positive_clv_rate": base_metrics["positive_clv_rate"],
            "filtered_bets": filtered_metrics["bet_count"],
            "filtered_roi": filtered_metrics["roi"],
            "filtered_positive_clv_rate": filtered_metrics["positive_clv_rate"],
            "report": str(output_dir / "clv_timing_filter_report.md"),
        }
    )


if __name__ == "__main__":
    main()
