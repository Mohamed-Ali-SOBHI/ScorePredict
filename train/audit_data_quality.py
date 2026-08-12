from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml_common import get_feature_cols


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_DATA_DIR = REPO_ROOT / "Data"
DEFAULT_DATASET = SCRIPT_DIR / "dataset_home.csv"
DEFAULT_PROTOCOL_DIR = SCRIPT_DIR / "output" / "experimental_protocol_targeted_favorite_fix"
DEFAULT_OUTPUT_JSON = SCRIPT_DIR / "output" / "data_quality_audit.json"
DEFAULT_OUTPUT_MD = SCRIPT_DIR / "output" / "data_quality_audit.md"

RAW_REQUIRED_COLUMNS = {
    "match_id",
    "date",
    "is_home",
    "team_id",
    "team_name",
    "result",
    "opponent_id",
    "opponent_name",
    "team_xG",
    "opponent_xG",
    "team_win_odds_open",
    "draw_odds_open",
    "opponent_win_odds_open",
}
DATASET_REQUIRED_COLUMNS = {
    "match_id",
    "date",
    "league",
    "season",
    "team_name",
    "opponent_name",
    "target",
    "market_home_win_odds_open",
    "market_draw_odds_open",
    "market_away_win_odds_open",
    "market_home_prob_open",
    "market_draw_prob_open",
    "market_away_prob_open",
}
MODEL_CLASS_ORDER = ["away_win", "draw", "home_win"]
MARKET_PROB_COLS_MODEL_ORDER = [
    "market_away_prob_open",
    "market_draw_prob_open",
    "market_home_prob_open",
]
MARKET_PROB_COLS_OLD_ORDER = [
    "market_home_prob_open",
    "market_draw_prob_open",
    "market_away_prob_open",
]


def resolve_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--protocol-dir", default=str(DEFAULT_PROTOCOL_DIR))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    return parser.parse_args()


def safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def season_from_file(path: Path) -> int | None:
    match = re.match(r"(\d{4})\s+", path.name)
    return int(match.group(1)) if match else None


def load_raw_rows(data_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    frames = []
    file_rows = []
    missing_required_by_file = {}
    for path in sorted(data_dir.glob("*/*.csv")):
        try:
            df = pd.read_csv(path)
        except Exception as exc:  # pragma: no cover - defensive audit reporting
            missing_required_by_file[str(path)] = [f"read_error:{exc}"]
            continue
        missing = sorted(RAW_REQUIRED_COLUMNS - set(df.columns))
        if missing:
            missing_required_by_file[str(path)] = missing
        league = path.parent.name
        season = season_from_file(path)
        df = df.copy()
        df["_source_file"] = str(path)
        df["league"] = league
        df["season"] = season
        frames.append(df)
        file_rows.append({"file": str(path), "rows": int(len(df)), "league": league, "season": season})

    raw = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if not raw.empty and "date" in raw.columns:
        raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    return raw, {
        "file_count": len(file_rows),
        "files": file_rows,
        "files_missing_required_columns": missing_required_by_file,
    }


def audit_raw_data(data_dir: Path) -> dict[str, Any]:
    raw, file_info = load_raw_rows(data_dir)
    if raw.empty:
        return {"status": "fail", "reason": "No raw CSV rows loaded", **file_info}

    odds_cols = ["team_win_odds_open", "draw_odds_open", "opponent_win_odds_open"]
    missing_odds = int(raw[odds_cols].isna().any(axis=1).sum()) if set(odds_cols).issubset(raw.columns) else None
    invalid_odds = (
        int((raw[odds_cols].apply(pd.to_numeric, errors="coerce") <= 1.0).any(axis=1).sum())
        if set(odds_cols).issubset(raw.columns)
        else None
    )
    duplicate_match_team = (
        int(raw.duplicated(["match_id", "team_id"]).sum())
        if {"match_id", "team_id"}.issubset(raw.columns)
        else None
    )
    side_counts = raw.groupby("match_id").size() if "match_id" in raw.columns else pd.Series(dtype=int)
    side_count_distribution = {str(int(k)): int(v) for k, v in side_counts.value_counts().sort_index().items()}

    result_values = raw["result"].dropna().astype(str).str.lower() if "result" in raw.columns else pd.Series(dtype=str)
    invalid_results = int((~result_values.isin(["w", "d", "l"])).sum()) if not result_values.empty else None

    by_league_season = (
        raw.groupby(["league", "season"], dropna=False)
        .agg(rows=("match_id", "size"), matches=("match_id", "nunique"))
        .reset_index()
        .sort_values(["league", "season"])
    )
    return {
        "status": "ok",
        **file_info,
        "rows": int(len(raw)),
        "unique_matches": int(raw["match_id"].nunique()) if "match_id" in raw.columns else None,
        "date_min": raw["date"].min().isoformat() if "date" in raw.columns and raw["date"].notna().any() else None,
        "date_max": raw["date"].max().isoformat() if "date" in raw.columns and raw["date"].notna().any() else None,
        "duplicate_match_team_rows": duplicate_match_team,
        "match_side_count_distribution": side_count_distribution,
        "matches_without_two_sides": int((side_counts != 2).sum()) if not side_counts.empty else None,
        "missing_opening_odds_rows": missing_odds,
        "invalid_opening_odds_rows": invalid_odds,
        "invalid_result_rows": invalid_results,
        "by_league_season": by_league_season.to_dict(orient="records"),
    }


def target_distribution(df: pd.DataFrame) -> dict[str, int]:
    mapping = {0: "away_win", 1: "draw", 2: "home_win"}
    counts = df["target"].dropna().astype(int).map(mapping).value_counts().to_dict()
    return {key: int(counts.get(key, 0)) for key in ["home_win", "draw", "away_win"]}


def audit_market_favorite_order(df: pd.DataFrame) -> dict[str, Any]:
    valid = df.dropna(subset=MARKET_PROB_COLS_MODEL_ORDER).copy()
    if valid.empty:
        return {"status": "fail", "reason": "No market probabilities available"}

    correct_idx = valid[MARKET_PROB_COLS_MODEL_ORDER].to_numpy().argmax(axis=1)
    old_idx = valid[MARKET_PROB_COLS_OLD_ORDER].to_numpy().argmax(axis=1)
    correct_labels = pd.Series(correct_idx).map(lambda idx: MODEL_CLASS_ORDER[int(idx)])
    old_labels = pd.Series(old_idx).map(lambda idx: MODEL_CLASS_ORDER[int(idx)])
    disagreement = correct_labels.to_numpy() != old_labels.to_numpy()
    favorite_counts = correct_labels.value_counts().to_dict()
    return {
        "status": "ok",
        "rows_checked": int(len(valid)),
        "correct_favorite_counts": {label: int(favorite_counts.get(label, 0)) for label in MODEL_CLASS_ORDER},
        "old_order_disagreement_rows": int(disagreement.sum()),
        "old_order_disagreement_rate": float(disagreement.mean()),
        "note": "Correct model order is away/draw/home. Old home/draw/away order flips home and away favorites.",
    }


def audit_dataset(dataset_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = pd.read_csv(dataset_path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    missing_required = sorted(DATASET_REQUIRED_COLUMNS - set(df.columns))
    completed = df.dropna(subset=["target"]).copy()
    odds_cols = [
        "market_home_win_odds_open",
        "market_draw_odds_open",
        "market_away_win_odds_open",
    ]
    prob_cols = [
        "market_home_prob_open",
        "market_draw_prob_open",
        "market_away_prob_open",
    ]
    odds_numeric = df[odds_cols].apply(pd.to_numeric, errors="coerce")
    prob_sum = df[prob_cols].sum(axis=1)
    raw_overround = (1.0 / odds_numeric).sum(axis=1)

    by_season = (
        completed.groupby("season")
        .agg(matches=("match_id", "nunique"), rows=("match_id", "size"))
        .reset_index()
        .sort_values("season")
    )
    by_league_season = (
        completed.groupby(["league", "season"])
        .agg(matches=("match_id", "nunique"), rows=("match_id", "size"))
        .reset_index()
        .sort_values(["league", "season"])
    )
    feature_cols = get_feature_cols(completed, include_draw_features=False)
    draw_feature_cols = get_feature_cols(completed, include_draw_features=True)
    algo_feature_cols = get_feature_cols(
        completed,
        include_draw_features=False,
        include_algo_features=True,
    )
    algo_draw_feature_cols = get_feature_cols(
        completed,
        include_draw_features=True,
        include_algo_features=True,
    )
    closing_feature_cols = get_feature_cols(
        completed,
        include_draw_features=False,
        include_closing_market_features=True,
    )
    consensus_feature_cols = get_feature_cols(
        completed,
        include_draw_features=False,
        include_consensus_market_features=True,
    )
    all_optional_feature_cols = get_feature_cols(
        completed,
        include_draw_features=False,
        include_algo_features=True,
        include_closing_market_features=True,
        include_consensus_market_features=True,
    )
    all_optional_draw_feature_cols = get_feature_cols(
        completed,
        include_draw_features=True,
        include_algo_features=True,
        include_closing_market_features=True,
        include_consensus_market_features=True,
    )
    feature_frame = completed[feature_cols]
    draw_feature_frame = completed[draw_feature_cols]
    top_missing = (
        feature_frame.isna().mean().sort_values(ascending=False).head(15).rename("missing_rate").reset_index()
    )
    top_missing_draw = (
        draw_feature_frame.isna().mean().sort_values(ascending=False).head(15).rename("missing_rate").reset_index()
    )
    numeric_values = completed[feature_cols].to_numpy(dtype=float)
    draw_numeric_values = completed[draw_feature_cols].to_numpy(dtype=float)
    algo_numeric_values = completed[algo_feature_cols].to_numpy(dtype=float)
    algo_draw_numeric_values = completed[algo_draw_feature_cols].to_numpy(dtype=float)
    all_optional_numeric_values = completed[all_optional_feature_cols].to_numpy(dtype=float)
    all_optional_draw_numeric_values = completed[all_optional_draw_feature_cols].to_numpy(dtype=float)

    return df, {
        "status": "ok" if not missing_required else "warn",
        "missing_required_columns": missing_required,
        "rows": int(len(df)),
        "completed_rows": int(len(completed)),
        "unique_matches": int(df["match_id"].nunique()),
        "duplicate_match_ids": int(df.duplicated("match_id").sum()),
        "date_min": df["date"].min().isoformat() if df["date"].notna().any() else None,
        "date_max": df["date"].max().isoformat() if df["date"].notna().any() else None,
        "season_min": int(df["season"].min()),
        "season_max": int(df["season"].max()),
        "season_2025_matches": int(df[df["season"].eq(2025)]["match_id"].nunique()),
        "season_2025_missing_opening_odds_rows": int(df[df["season"].eq(2025)][odds_cols].isna().any(axis=1).sum()),
        "missing_opening_odds_rows": int(df[odds_cols].isna().any(axis=1).sum()),
        "invalid_opening_odds_rows": int((odds_numeric <= 1.0).any(axis=1).sum()),
        "market_probability_sum_min": safe_float(prob_sum.min()),
        "market_probability_sum_max": safe_float(prob_sum.max()),
        "market_probability_sum_bad_rows": int((~np.isclose(prob_sum, 1.0, atol=1e-8)).sum()),
        "raw_opening_overround_min": safe_float(raw_overround.min()),
        "raw_opening_overround_median": safe_float(raw_overround.median()),
        "raw_opening_overround_max": safe_float(raw_overround.max()),
        "target_distribution": target_distribution(completed),
        "feature_count_multiclass": int(len(feature_cols)),
        "feature_count_draw": int(len(draw_feature_cols)),
        "feature_count_multiclass_with_algo": int(len(algo_feature_cols)),
        "feature_count_draw_with_algo": int(len(algo_draw_feature_cols)),
        "feature_count_multiclass_with_closing": int(len(closing_feature_cols)),
        "feature_count_multiclass_with_consensus": int(len(consensus_feature_cols)),
        "feature_count_multiclass_with_all_optional": int(len(all_optional_feature_cols)),
        "feature_count_draw_with_all_optional": int(len(all_optional_draw_feature_cols)),
        "feature_infinite_values_multiclass": int(np.isinf(numeric_values).sum()),
        "feature_infinite_values_draw": int(np.isinf(draw_numeric_values).sum()),
        "feature_infinite_values_multiclass_with_algo": int(np.isinf(algo_numeric_values).sum()),
        "feature_infinite_values_draw_with_algo": int(np.isinf(algo_draw_numeric_values).sum()),
        "feature_infinite_values_multiclass_with_all_optional": int(np.isinf(all_optional_numeric_values).sum()),
        "feature_infinite_values_draw_with_all_optional": int(np.isinf(all_optional_draw_numeric_values).sum()),
        "feature_top_missing_multiclass": top_missing.rename(columns={"index": "feature"}).to_dict(orient="records"),
        "feature_top_missing_draw": top_missing_draw.rename(columns={"index": "feature"}).to_dict(orient="records"),
        "market_favorite_order_audit": audit_market_favorite_order(df),
        "by_season": by_season.to_dict(orient="records"),
        "by_league_season": by_league_season.to_dict(orient="records"),
    }


def audit_protocol(protocol_dir: Path) -> dict[str, Any]:
    registry_path = protocol_dir / "experiment_registry.csv"
    leaderboard_path = protocol_dir / "experiment_leaderboard.csv"
    if not registry_path.exists() or not leaderboard_path.exists():
        return {"status": "missing", "protocol_dir": str(protocol_dir)}

    registry = pd.read_csv(registry_path)
    leaderboard = pd.read_csv(leaderboard_path)
    top = leaderboard.sort_values("rank").iloc[0].to_dict() if not leaderboard.empty else {}
    return {
        "status": "ok",
        "protocol_dir": str(protocol_dir),
        "run_count": int(len(registry)),
        "status_counts": {str(k): int(v) for k, v in registry["status"].value_counts().items()},
        "folds": sorted(str(value) for value in registry["fold"].unique()),
        "experiments": sorted(str(value) for value in registry["experiment_name"].unique()),
        "top_experiment": {
            "name": top.get("experiment_name"),
            "eligible": bool(top.get("eligible")) if top else None,
            "total_test_bets": int(top.get("total_test_bets")) if top else None,
            "total_test_profit": safe_float(top.get("total_test_profit")) if top else None,
            "pooled_test_roi": safe_float(top.get("pooled_test_roi")) if top else None,
            "negative_folds": int(top.get("negative_folds")) if top else None,
        },
    }


def build_markdown(payload: dict[str, Any]) -> str:
    raw = payload["raw_data"]
    ds = payload["dataset"]
    protocol = payload["protocol"]
    favorite = ds["market_favorite_order_audit"]

    lines = [
        "# Data quality audit",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Raw data",
        "",
        f"- Status: `{raw['status']}`",
        f"- CSV files: `{raw.get('file_count')}`",
        f"- Rows: `{raw.get('rows')}`",
        f"- Unique matches: `{raw.get('unique_matches')}`",
        f"- Date range: `{raw.get('date_min')}` -> `{raw.get('date_max')}`",
        f"- Duplicate `(match_id, team_id)` rows: `{raw.get('duplicate_match_team_rows')}`",
        f"- Matches without exactly two team-side rows: `{raw.get('matches_without_two_sides')}`",
        f"- Rows missing opening odds: `{raw.get('missing_opening_odds_rows')}`",
        f"- Rows with invalid opening odds: `{raw.get('invalid_opening_odds_rows')}`",
        f"- Rows with invalid results: `{raw.get('invalid_result_rows')}`",
        "",
        "## Preprocessed dataset",
        "",
        f"- Status: `{ds['status']}`",
        f"- Rows: `{ds['rows']}`",
        f"- Completed rows: `{ds['completed_rows']}`",
        f"- Unique matches: `{ds['unique_matches']}`",
        f"- Duplicate match ids: `{ds['duplicate_match_ids']}`",
        f"- Date range: `{ds['date_min']}` -> `{ds['date_max']}`",
        f"- Seasons: `{ds['season_min']}` -> `{ds['season_max']}`",
        f"- Season 2025 matches: `{ds['season_2025_matches']}`",
        f"- Season 2025 rows missing opening odds: `{ds['season_2025_missing_opening_odds_rows']}`",
        f"- Rows missing opening odds: `{ds['missing_opening_odds_rows']}`",
        f"- Invalid opening odds rows: `{ds['invalid_opening_odds_rows']}`",
        f"- Market probability sum bad rows: `{ds['market_probability_sum_bad_rows']}`",
        f"- Opening overround median: `{ds['raw_opening_overround_median']:.4f}`",
        f"- Target distribution: `{ds['target_distribution']}`",
        "",
        "## Model input audit",
        "",
        f"- Multiclass feature count: `{ds['feature_count_multiclass']}`",
        f"- Draw feature count: `{ds['feature_count_draw']}`",
        f"- Multiclass feature count with algo: `{ds['feature_count_multiclass_with_algo']}`",
        f"- Draw feature count with algo: `{ds['feature_count_draw_with_algo']}`",
        f"- Multiclass feature count with closing: `{ds['feature_count_multiclass_with_closing']}`",
        f"- Multiclass feature count with consensus: `{ds['feature_count_multiclass_with_consensus']}`",
        f"- Multiclass feature count with all optional: `{ds['feature_count_multiclass_with_all_optional']}`",
        f"- Draw feature count with all optional: `{ds['feature_count_draw_with_all_optional']}`",
        f"- Infinite feature values, multiclass: `{ds['feature_infinite_values_multiclass']}`",
        f"- Infinite feature values, draw: `{ds['feature_infinite_values_draw']}`",
        f"- Infinite feature values, multiclass with algo: `{ds['feature_infinite_values_multiclass_with_algo']}`",
        f"- Infinite feature values, draw with algo: `{ds['feature_infinite_values_draw_with_algo']}`",
        f"- Infinite feature values, multiclass with all optional: `{ds['feature_infinite_values_multiclass_with_all_optional']}`",
        f"- Infinite feature values, draw with all optional: `{ds['feature_infinite_values_draw_with_all_optional']}`",
        "",
        "## Market favorite order audit",
        "",
        f"- Status: `{favorite['status']}`",
        f"- Rows checked: `{favorite.get('rows_checked')}`",
        f"- Correct favorite counts: `{favorite.get('correct_favorite_counts')}`",
        f"- Old-order disagreement rows: `{favorite.get('old_order_disagreement_rows')}`",
        f"- Old-order disagreement rate: `{favorite.get('old_order_disagreement_rate'):.4f}`",
        f"- Note: {favorite.get('note')}",
        "",
        "## Protocol audit",
        "",
        f"- Status: `{protocol['status']}`",
        f"- Run count: `{protocol.get('run_count')}`",
        f"- Status counts: `{protocol.get('status_counts')}`",
        f"- Top experiment: `{protocol.get('top_experiment', {}).get('name')}`",
        f"- Top pooled ROI: `{protocol.get('top_experiment', {}).get('pooled_test_roi')}`",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    data_dir = resolve_path(args.data_dir)
    dataset_path = resolve_path(args.dataset)
    protocol_dir = resolve_path(args.protocol_dir)
    output_json = resolve_path(args.output_json)
    output_md = resolve_path(args.output_md)

    _, dataset_audit = audit_dataset(dataset_path)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "raw_data": audit_raw_data(data_dir),
        "dataset": dataset_audit,
        "protocol": audit_protocol(protocol_dir),
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    output_md.write_text(build_markdown(payload), encoding="utf-8")

    print(
        {
            "output_json": str(output_json),
            "output_md": str(output_md),
            "raw_status": payload["raw_data"]["status"],
            "dataset_status": payload["dataset"]["status"],
            "season_2025_matches": payload["dataset"]["season_2025_matches"],
            "season_2025_missing_opening_odds_rows": payload["dataset"]["season_2025_missing_opening_odds_rows"],
            "protocol_status": payload["protocol"]["status"],
        }
    )


if __name__ == "__main__":
    main()
