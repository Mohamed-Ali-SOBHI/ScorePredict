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
from sklearn.preprocessing import StandardScaler

from validation_metrics import summarize_bets


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_PATH = SCRIPT_DIR / "dataset_home.csv"
DEFAULT_BETS_PATH = (
    SCRIPT_DIR
    / "output"
    / "experimental_protocol_targeted_favorite_fix"
    / "best_strategy_bets.csv"
)
DEFAULT_TIMING_SCORES_PATH = (
    SCRIPT_DIR
    / "output"
    / "clv_timing_filter_draw_consensus_conservative_keep"
    / "scored_bets.csv"
)
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output" / "meta_filter_draw_consensus"
PASS_THROUGH_THRESHOLD = -1.0


BASE_NUMERIC_FEATURES = [
    "selected_odds",
    "predicted_probability",
    "market_probability",
    "edge",
    "expected_value",
    "raw_model_probability",
    "value_score",
    "raw_expected_value",
    "multiclass_draw_probability",
    "binary_draw_probability",
    "draw_model_disagreement",
    "strategy_count",
    "timing_positive_clv_probability",
]

OPENING_CONTEXT_FEATURES = [
    "market_overround_open",
    "market_home_prob_open",
    "market_draw_prob_open",
    "market_away_prob_open",
    "market_home_minus_away_prob_open",
    "market_non_draw_prob_open",
    "market_favorite_prob_open",
    "market_favorite_gap_open",
    "market_entropy_open",
    "draw_abs_elo_gap",
    "draw_elo_parity",
    "draw_abs_xG_advantage_5_carry",
    "draw_abs_defensive_advantage_5_carry",
    "draw_abs_relative_form_5_carry",
    "draw_total_xG_last_5_carry",
    "draw_total_xG_against_last_5_carry",
    "draw_market_home_away_gap_open",
    "draw_market_triplet_std_open",
    "draw_combined_draw_rate_10_carry",
    "draw_draw_rate_gap_10_carry",
    "market_home_win_consensus_odds_open",
    "market_draw_consensus_odds_open",
    "market_away_win_consensus_odds_open",
    "market_home_prob_consensus_open",
    "market_draw_prob_consensus_open",
    "market_away_prob_consensus_open",
    "market_draw_consensus_odds_diff_open",
]

LEAKY_PATTERNS = [
    "_close",
    "_move_close_minus_open",
    "profit",
    "won_bet",
    "target",
    "result",
]


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
        return np.column_stack([1.0 - positive, positive])


def resolve_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk-forward meta-filter for bets already selected by a champion strategy."
    )
    parser.add_argument("--data", default=str(DEFAULT_DATA_PATH))
    parser.add_argument("--bets", default=str(DEFAULT_BETS_PATH))
    parser.add_argument("--timing-scores", default=str(DEFAULT_TIMING_SCORES_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--start-val-season", type=int, default=2022)
    parser.add_argument("--end-val-season", type=int, default=2024)
    parser.add_argument("--min-train-bets", type=int, default=80)
    parser.add_argument("--min-val-bets", type=int, default=35)
    parser.add_argument("--min-val-keep-rate", type=float, default=0.25)
    parser.add_argument("--thresholds", default="auto")
    parser.add_argument("--target", choices=["win", "positive_clv", "win_and_positive_clv"], default="win")
    parser.add_argument("--include-timing-score", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-opening-context", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-algo-features", action="store_true")
    parser.add_argument("--pass-through-insufficient-history", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--n-iterations", type=int, default=120)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bootstrap-iterations", type=int, default=5000)
    return parser.parse_args()


def build_folds(bets: pd.DataFrame, start_val_season: int, end_val_season: int) -> list[Fold]:
    seasons = {int(value) for value in bets["season"].dropna().unique()}
    folds = []
    for val_season in range(start_val_season, end_val_season + 1):
        test_season = val_season + 1
        if test_season in seasons:
            folds.append(Fold(val_season=val_season, test_season=test_season))
    if not folds:
        raise ValueError("No valid folds found")
    return folds


def parse_thresholds(raw: str, scores: pd.Series) -> list[float]:
    if raw.strip().lower() != "auto":
        values = [float(value.strip()) for value in raw.split(",") if value.strip()]
        if not values:
            raise ValueError("--thresholds must contain at least one value or 'auto'")
        return sorted(set(values))
    quantiles = np.linspace(0.05, 0.90, 18)
    values = scores.dropna().quantile(quantiles).to_numpy(dtype=float)
    return sorted(set(float(value) for value in values if np.isfinite(value)))


def load_base_bets(path: Path) -> pd.DataFrame:
    bets = pd.read_csv(path)
    bets["date"] = pd.to_datetime(bets["date"])
    bets["season"] = pd.to_numeric(bets["season"], errors="raise").astype(int)
    if "test_season" in bets.columns:
        bets["test_season"] = pd.to_numeric(bets["test_season"], errors="coerce").astype("Int64")
    else:
        bets["test_season"] = bets["season"].astype("Int64")
    if "bet_key" not in bets.columns:
        bets["bet_key"] = bets["match_id"].astype(str) + "|" + bets["selected_outcome"].astype(str)
    return bets


def merge_missing_context(
    bets: pd.DataFrame,
    data: pd.DataFrame,
    *,
    include_opening_context: bool,
    include_algo_features: bool,
) -> pd.DataFrame:
    wanted = []
    if include_opening_context:
        wanted.extend(OPENING_CONTEXT_FEATURES)
    if include_algo_features:
        wanted.extend([column for column in data.columns if column.startswith("algo_")])

    missing = [column for column in wanted if column in data.columns and column not in bets.columns]
    if not missing:
        return bets
    context = data[["match_id", *missing]].drop_duplicates("match_id")
    return bets.merge(context, on="match_id", how="left", validate="many_to_one")


def merge_timing_scores(bets: pd.DataFrame, timing_scores_path: Path, *, enabled: bool) -> pd.DataFrame:
    if not enabled or not timing_scores_path.exists():
        return bets
    timing = pd.read_csv(timing_scores_path)
    if "bet_key" not in timing.columns:
        timing["bet_key"] = timing["match_id"].astype(str) + "|" + timing["selected_outcome"].astype(str)
    keep = [
        column
        for column in [
            "bet_key",
            "timing_positive_clv_probability",
            "timing_threshold",
            "timing_filter_pass",
        ]
        if column in timing.columns
    ]
    timing = timing[keep].drop_duplicates("bet_key")
    merged = bets.merge(timing, on="bet_key", how="left", validate="many_to_one")
    if "timing_filter_pass" in merged.columns:
        merged["timing_filter_pass"] = merged["timing_filter_pass"].astype(float)
    return merged


def add_derived_columns(bets: pd.DataFrame) -> pd.DataFrame:
    result = bets.copy()
    if {"multiclass_draw_probability", "binary_draw_probability"}.issubset(result.columns):
        result["draw_model_disagreement"] = (
            pd.to_numeric(result["multiclass_draw_probability"], errors="coerce")
            - pd.to_numeric(result["binary_draw_probability"], errors="coerce")
        ).abs()
    else:
        result["draw_model_disagreement"] = np.nan
    if "strategy_names" in result.columns:
        result["strategy_count"] = result["strategy_names"].fillna("").astype(str).str.count(r"\|") + 1
    else:
        result["strategy_count"] = 1.0
    if "positive_clv" in result.columns:
        result["positive_clv"] = result["positive_clv"].astype(bool)
    return result


def add_target_column(bets: pd.DataFrame, target: str) -> pd.DataFrame:
    result = bets.copy()
    if target == "win":
        result["meta_target"] = result["won_bet"].astype(bool).astype(int)
    elif target == "positive_clv":
        if "positive_clv" not in result.columns:
            raise ValueError("positive_clv target requires a bets file with CLV columns")
        result["meta_target"] = result["positive_clv"].astype(bool).astype(int)
    elif target == "win_and_positive_clv":
        if "positive_clv" not in result.columns:
            raise ValueError("win_and_positive_clv target requires a bets file with CLV columns")
        result["meta_target"] = (
            result["won_bet"].astype(bool) & result["positive_clv"].astype(bool)
        ).astype(int)
    else:
        raise ValueError(f"Unsupported target: {target}")
    return result


def is_leaky_column(column: str) -> bool:
    return any(pattern in column for pattern in LEAKY_PATTERNS)


def feature_columns(bets: pd.DataFrame, *, include_timing_score: bool) -> list[str]:
    candidates = [column for column in BASE_NUMERIC_FEATURES if column in bets.columns]
    if not include_timing_score:
        candidates = [column for column in candidates if not column.startswith("timing_")]

    candidates.extend(
        column
        for column in OPENING_CONTEXT_FEATURES
        if column in bets.columns and not is_leaky_column(column)
    )
    candidates.extend(
        column
        for column in bets.columns
        if column.startswith("algo_") and not is_leaky_column(column)
    )
    if "timing_filter_pass" in bets.columns and include_timing_score:
        candidates.append("timing_filter_pass")

    numeric_candidates = [
        column
        for column in dict.fromkeys(candidates)
        if column in bets.columns and pd.api.types.is_numeric_dtype(bets[column])
    ]
    return numeric_candidates


def design_matrix(frame: pd.DataFrame, numeric_features: list[str], dummy_columns: list[str] | None = None) -> pd.DataFrame:
    numeric = frame[numeric_features].copy()
    categoricals = pd.get_dummies(
        frame[["league", "selected_outcome"]].astype(str),
        prefix=["league", "outcome"],
        dtype=float,
    )
    design = pd.concat([numeric, categoricals], axis=1)
    if dummy_columns is not None:
        design = design.reindex(columns=[*numeric_features, *dummy_columns], fill_value=0.0)
    return design


def fit_model(train: pd.DataFrame, *, features: list[str], seed: int, n_iterations: int) -> tuple[object, list[str]]:
    x_train_initial = design_matrix(train, features)
    dummy_columns = [column for column in x_train_initial.columns if column not in features]
    y = train["meta_target"].astype(int)
    if y.nunique() < 2:
        return ConstantProbabilityModel(float(y.mean()) if len(y) else 0.5), dummy_columns

    model = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler(with_mean=False)),
            (
                "classifier",
                HistGradientBoostingClassifier(
                    max_iter=n_iterations,
                    learning_rate=0.035,
                    max_leaf_nodes=9,
                    l2_regularization=0.10,
                    random_state=seed,
                ),
            ),
        ]
    )
    model.fit(x_train_initial, y)
    return model, dummy_columns


def score_model(model: object, frame: pd.DataFrame, *, features: list[str], dummy_columns: list[str]) -> np.ndarray:
    x = design_matrix(frame, features, dummy_columns=dummy_columns)
    return np.asarray(model.predict_proba(x)[:, 1], dtype=float)


def choose_threshold(
    val: pd.DataFrame,
    thresholds: list[float],
    *,
    min_val_bets: int,
    min_val_keep_rate: float,
) -> dict[str, Any]:
    base_count = len(val)
    candidates = []
    for threshold in thresholds:
        kept = val[val["meta_keep_probability"] >= threshold].copy()
        keep_rate = len(kept) / float(base_count) if base_count else 0.0
        if len(kept) < min_val_bets or keep_rate < min_val_keep_rate:
            continue
        candidates.append(
            {
                "threshold": threshold,
                "val_bets": int(len(kept)),
                "val_keep_rate": float(keep_rate),
                "val_profit": float(kept["profit"].sum()),
                "val_roi": float(kept["profit"].mean()),
                "val_hit_rate": float(kept["won_bet"].astype(bool).mean()),
                "val_avg_probability": float(kept["meta_keep_probability"].mean()),
            }
        )
    if candidates:
        return sorted(
            candidates,
            key=lambda row: (row["val_roi"], row["val_profit"], row["val_bets"]),
            reverse=True,
        )[0]
    return {
        "threshold": PASS_THROUGH_THRESHOLD,
        "val_bets": base_count,
        "val_keep_rate": 1.0,
        "val_profit": float(val["profit"].sum()),
        "val_roi": float(val["profit"].mean()) if base_count else None,
        "val_hit_rate": float(val["won_bet"].astype(bool).mean()) if base_count else None,
        "val_avg_probability": float(val["meta_keep_probability"].mean()) if base_count else None,
        "fallback": True,
    }


def metric_summary(bets: pd.DataFrame, *, args: argparse.Namespace) -> dict[str, Any]:
    metrics = summarize_bets(
        bets,
        iterations=args.bootstrap_iterations,
        confidence_level=0.95,
        seed=args.seed,
    )
    if "positive_clv" in bets.columns and not bets.empty:
        metrics["positive_clv_rate"] = float(bets["positive_clv"].astype(bool).mean())
    else:
        metrics["positive_clv_rate"] = None
    if "clv_odds_diff" in bets.columns and not bets.empty:
        metrics["avg_clv_odds_diff"] = float(pd.to_numeric(bets["clv_odds_diff"], errors="coerce").mean())
    else:
        metrics["avg_clv_odds_diff"] = None
    if "meta_keep_probability" in bets.columns and not bets.empty:
        metrics["avg_meta_keep_probability"] = float(bets["meta_keep_probability"].mean())
    else:
        metrics["avg_meta_keep_probability"] = None
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
    path: Path,
    *,
    args: argparse.Namespace,
    feature_count: int,
    fold_rows: list[dict[str, Any]],
    base_metrics: dict[str, Any],
    filtered_metrics: dict[str, Any],
) -> None:
    rows = [
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
            "portfolio": "meta_filtered",
            "bets": filtered_metrics["bet_count"],
            "profit": filtered_metrics["total_profit"],
            "roi": filtered_metrics["roi"],
            "prob_roi_positive": filtered_metrics["bootstrap_prob_roi_positive"],
            "positive_clv_rate": filtered_metrics["positive_clv_rate"],
            "avg_clv_odds_diff": filtered_metrics["avg_clv_odds_diff"],
        },
    ]
    lines = [
        "# Meta-filter protocol",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Protocol",
        "",
        "- The base portfolio is already selected by the champion strategy.",
        "- The meta-filter trains only on previous base-portfolio bets.",
        "- The threshold is selected on the validation season.",
        "- The next season is tested without using its results.",
        f"- Target: `{args.target}`",
        f"- Feature count: `{feature_count}`",
        f"- Include timing score: `{args.include_timing_score}`",
        f"- Include opening context: `{args.include_opening_context}`",
        f"- Include algo features: `{args.include_algo_features}`",
        "",
        "## Aggregate",
        "",
        markdown_table(
            rows,
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
                "status",
                "threshold",
                "base_bets",
                "base_roi",
                "filtered_bets",
                "filtered_roi",
                "filtered_profit",
                "filtered_positive_clv_rate",
            ],
        ),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    data_path = resolve_path(args.data)
    bets_path = resolve_path(args.bets)
    timing_scores_path = resolve_path(args.timing_scores)
    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    data = pd.read_csv(data_path)
    bets = load_base_bets(bets_path)
    bets = merge_timing_scores(bets, timing_scores_path, enabled=args.include_timing_score)
    bets = merge_missing_context(
        bets,
        data,
        include_opening_context=args.include_opening_context,
        include_algo_features=args.include_algo_features,
    )
    bets = add_derived_columns(bets)
    bets = add_target_column(bets, args.target)

    features = feature_columns(bets, include_timing_score=args.include_timing_score)
    if not features:
        raise ValueError("No meta-filter features available")
    folds = build_folds(bets, args.start_val_season, args.end_val_season)

    scored_frames = []
    filtered_frames = []
    fold_rows = []
    for fold in folds:
        train = bets[bets["season"] < fold.val_season].copy()
        val = bets[bets["season"] == fold.val_season].copy()
        test = bets[bets["season"] == fold.test_season].copy()
        status = "ok"
        if len(train) < args.min_train_bets or val.empty or test.empty:
            if not args.pass_through_insufficient_history:
                continue
            status = "pass_through_insufficient_history"
            test = test.copy()
            test["meta_keep_probability"] = np.nan
            test["meta_threshold"] = PASS_THROUGH_THRESHOLD
            test["meta_filter_pass"] = True
            filtered = test.copy()
            threshold_row = {
                "threshold": PASS_THROUGH_THRESHOLD,
                "val_bets": int(len(val)),
                "val_keep_rate": 1.0 if len(val) else None,
                "val_roi": float(val["profit"].mean()) if len(val) else None,
            }
        else:
            model, dummy_columns = fit_model(
                train,
                features=features,
                seed=args.seed + fold.val_season,
                n_iterations=args.n_iterations,
            )
            val = val.copy()
            val["meta_keep_probability"] = score_model(model, val, features=features, dummy_columns=dummy_columns)
            thresholds = parse_thresholds(args.thresholds, val["meta_keep_probability"])
            threshold_row = choose_threshold(
                val,
                thresholds,
                min_val_bets=args.min_val_bets,
                min_val_keep_rate=args.min_val_keep_rate,
            )
            test = test.copy()
            test["meta_keep_probability"] = score_model(model, test, features=features, dummy_columns=dummy_columns)
            test["meta_threshold"] = threshold_row["threshold"]
            test["meta_filter_pass"] = test["meta_keep_probability"] >= threshold_row["threshold"]
            filtered = test[test["meta_filter_pass"]].copy()

        base_fold_metrics = metric_summary(test, args=args)
        filtered_fold_metrics = metric_summary(filtered, args=args)
        row = {
            "fold": fold.label,
            "status": status,
            "threshold": threshold_row["threshold"],
            "val_bets": threshold_row.get("val_bets"),
            "val_keep_rate": threshold_row.get("val_keep_rate"),
            "val_roi": threshold_row.get("val_roi"),
            "base_bets": base_fold_metrics["bet_count"],
            "base_profit": base_fold_metrics["total_profit"],
            "base_roi": base_fold_metrics["roi"],
            "filtered_bets": filtered_fold_metrics["bet_count"],
            "filtered_profit": filtered_fold_metrics["total_profit"],
            "filtered_roi": filtered_fold_metrics["roi"],
            "filtered_positive_clv_rate": filtered_fold_metrics["positive_clv_rate"],
        }
        print(row)
        fold_rows.append(row)
        scored_frames.append(test)
        filtered_frames.append(filtered)

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
        "timing_scores_path": str(timing_scores_path),
        "feature_count": len(features),
        "features": features,
        "base_metrics": base_metrics,
        "filtered_metrics": filtered_metrics,
        "folds": fold_rows,
    }
    (output_dir / "meta_filter_report.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    write_report(
        output_dir / "meta_filter_report.md",
        args=args,
        feature_count=len(features),
        fold_rows=fold_rows,
        base_metrics=base_metrics,
        filtered_metrics=filtered_metrics,
    )
    print(
        {
            "base_bets": base_metrics["bet_count"],
            "base_roi": base_metrics["roi"],
            "filtered_bets": filtered_metrics["bet_count"],
            "filtered_roi": filtered_metrics["roi"],
            "filtered_profit": filtered_metrics["total_profit"],
            "report": str(output_dir / "meta_filter_report.md"),
        }
    )


if __name__ == "__main__":
    main()
