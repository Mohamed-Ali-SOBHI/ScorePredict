from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from data_pipeline.market_data import is_home_mask, normalize_team_name
from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME, PRODUCTION_FREEZE_DATE
from train.make_dataset import load_team_match_rows


DEFAULT_LEDGER_PATH = SCRIPT_DIR / "output" / "live_portfolio_bet_log.csv"
DEFAULT_EVALUATION_PATH = SCRIPT_DIR / "output" / "live_portfolio_evaluation.csv"
DEFAULT_SUMMARY_PATH = SCRIPT_DIR / "output" / "live_portfolio_evaluation_summary.json"
DEFAULT_DATA_DIR = REPO_ROOT / "Data"

OUTCOME_FROM_HOME_RESULT = {
    "w": "home_win",
    "d": "draw",
    "l": "away_win",
}


def normalize_date(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp.normalize()


def normalize_date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, utc=True).dt.tz_localize(None).dt.normalize()


def numeric_column(frame: pd.DataFrame, column: str, default: float) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def resolve_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (Path.cwd() / candidate).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER_PATH))
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--freeze-date", default=PRODUCTION_FREEZE_DATE)
    parser.add_argument("--portfolio", default=DEFAULT_PORTFOLIO_NAME)
    parser.add_argument("--all-portfolios", action="store_true")
    parser.add_argument("--include-trends", action="store_true")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--output", default=str(DEFAULT_EVALUATION_PATH))
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY_PATH))
    parser.add_argument("--update-ledger", action="store_true")
    return parser.parse_args()


def load_home_results(data_dir: Path) -> pd.DataFrame:
    rows = load_team_match_rows(str(data_dir))
    home = rows.loc[is_home_mask(rows["is_home"])].copy()
    home = home[home["result"].notna()].copy()
    score_frames: list[pd.DataFrame] = []
    score_columns = ["match_id", "is_home", "team_goals", "opponent_goals"]
    for path in data_dir.rglob("*.csv"):
        header = set(pd.read_csv(path, nrows=0).columns)
        if set(score_columns).issubset(header):
            score_frames.append(pd.read_csv(path, usecols=score_columns))
    if score_frames:
        scores = pd.concat(score_frames, ignore_index=True)
        scores = scores.loc[is_home_mask(scores["is_home"])].drop_duplicates("match_id", keep="last")
        home = home.merge(scores[["match_id", "team_goals", "opponent_goals"]], on="match_id", how="left")
    else:
        home["team_goals"] = pd.NA
        home["opponent_goals"] = pd.NA
    home["match_date"] = normalize_date_series(home["date"])
    home["home_team_norm"] = home["team_name"].map(normalize_team_name)
    home["away_team_norm"] = home["opponent_name"].map(normalize_team_name)
    home["actual_outcome"] = home["result"].map(OUTCOME_FROM_HOME_RESULT)
    home["actual_home_score"] = pd.to_numeric(home["team_goals"], errors="coerce").astype("Int64")
    home["actual_away_score"] = pd.to_numeric(home["opponent_goals"], errors="coerce").astype("Int64")
    home = home[
        [
            "match_id",
            "match_date",
            "league",
            "team_name",
            "opponent_name",
            "result",
            "actual_outcome",
            "actual_home_score",
            "actual_away_score",
            "home_team_norm",
            "away_team_norm",
        ]
    ].rename(
        columns={
            "team_name": "actual_home_team",
            "opponent_name": "actual_away_team",
            "result": "actual_result",
        }
    )
    return home.drop_duplicates(
        subset=["league", "match_date", "home_team_norm", "away_team_norm"],
        keep="last",
    )


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"", "0", "0.0", "false", "no", "none", "nan", "<na>"}


def prepare_ledger(
    ledger: pd.DataFrame,
    freeze_date: pd.Timestamp,
    *,
    portfolio_name: str | None = None,
    recommended_only: bool = True,
) -> pd.DataFrame:
    required = {"date", "league", "team_name", "opponent_name", "selected_outcome", "selected_odds"}
    missing = sorted(required - set(ledger.columns))
    if missing:
        raise ValueError(f"Ledger is missing required columns: {', '.join(missing)}")

    prepared = ledger.copy()
    prepared["date"] = pd.to_datetime(prepared["date"], utc=True).dt.tz_localize(None)
    prepared["match_date"] = prepared["date"].dt.normalize()
    prepared["home_team_norm"] = prepared["team_name"].map(normalize_team_name)
    prepared["away_team_norm"] = prepared["opponent_name"].map(normalize_team_name)
    recalculated_columns = [
        "actual_home_team",
        "actual_away_team",
        "actual_result",
        "actual_outcome",
        "actual_home_score",
        "actual_away_score",
        "match_found",
        "won_live_bet",
        "realized_profit_units",
    ]
    prepared = prepared.drop(columns=[column for column in recalculated_columns if column in prepared.columns])
    prepared = prepared[prepared["match_date"] >= normalize_date(freeze_date)].copy()
    if portfolio_name:
        if "portfolio_name" not in prepared.columns:
            raise ValueError("Ledger is missing required column: portfolio_name")
        prepared = prepared[prepared["portfolio_name"].astype(str) == portfolio_name].copy()
    if recommended_only:
        if "recommended" not in prepared.columns:
            raise ValueError("Ledger is missing required column: recommended")
        recommended_mask = prepared["recommended"].map(_truthy).astype(bool)
        prepared = prepared.loc[recommended_mask].copy()
    return prepared


def evaluate_rows(
    ledger: pd.DataFrame,
    results: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp,
) -> pd.DataFrame:
    ledger = ledger.copy()
    results = results.copy()
    ledger["match_date"] = normalize_date_series(ledger["match_date"])
    results["match_date"] = normalize_date_series(results["match_date"])
    as_of_date = normalize_date(as_of_date)
    merge_keys = ["league", "match_date", "home_team_norm", "away_team_norm"]
    evaluated = ledger.merge(results, on=merge_keys, how="left", validate="many_to_one")
    evaluated["match_found"] = evaluated["actual_outcome"].notna()

    selected = evaluated["selected_outcome"].astype(str)
    actual = evaluated["actual_outcome"].astype(str)
    evaluated["won_live_bet"] = evaluated["match_found"] & (selected == actual)

    selected_odds = pd.to_numeric(evaluated["selected_odds"], errors="coerce")
    stake_eur = numeric_column(evaluated, "stake_eur", 1.0)
    settled_profit_units = np.where(evaluated["won_live_bet"], selected_odds - 1.0, -1.0)
    evaluated["realized_profit_units"] = np.where(
        evaluated["match_found"],
        settled_profit_units,
        np.nan,
    )
    evaluated["realized_profit"] = evaluated["realized_profit_units"] * stake_eur

    latest_result_date = results["match_date"].max() if not results.empty else pd.NaT
    evaluated["result_status"] = "unmatched"
    evaluated.loc[evaluated["match_date"] > as_of_date, "result_status"] = "pending"
    if pd.notna(latest_result_date):
        evaluated.loc[
            (~evaluated["match_found"])
            & (evaluated["match_date"] <= as_of_date)
            & (evaluated["match_date"] > latest_result_date),
            "result_status",
        ] = "pending_data_refresh"
    evaluated.loc[evaluated["match_found"] & evaluated["won_live_bet"], "result_status"] = "won"
    evaluated.loc[evaluated["match_found"] & ~evaluated["won_live_bet"], "result_status"] = "lost"
    return evaluated


def build_summary(
    evaluated: pd.DataFrame,
    *,
    freeze_date: str,
    as_of_date: str,
    portfolio_name: str | None = None,
    recommended_only: bool = True,
) -> dict[str, object]:
    prediction_keys = ["date", "league", "team_name", "opponent_name", "selected_outcome"]
    unique_predictions = evaluated.drop_duplicates(subset=prediction_keys, keep="first").copy()
    settled = unique_predictions[unique_predictions["result_status"].isin(["won", "lost"])].copy()
    stake = numeric_column(settled, "stake_eur", 1.0)
    total_stake = float(stake.sum()) if not settled.empty else 0.0
    total_profit_eur = float(settled["realized_profit"].sum()) if not settled.empty else 0.0
    return {
        "portfolio_name": portfolio_name or "all",
        "recommended_only": recommended_only,
        "freeze_date": freeze_date,
        "as_of_date": as_of_date,
        "ledger_rows_after_freeze": int(len(evaluated)),
        "published_predictions": int(len(unique_predictions)),
        "settled_bets": int(len(settled)),
        "won_bets": int((settled["result_status"] == "won").sum()) if not settled.empty else 0,
        "lost_bets": int((settled["result_status"] == "lost").sum()) if not settled.empty else 0,
        "void_bets": int((unique_predictions["result_status"] == "void").sum()),
        "pending_bets": int((unique_predictions["result_status"] == "pending").sum()),
        "pending_data_refresh_bets": int((unique_predictions["result_status"] == "pending_data_refresh").sum()),
        "unmatched_bets": int((unique_predictions["result_status"] == "unmatched").sum()),
        "profit_units": float(settled["realized_profit_units"].sum()) if not settled.empty else 0.0,
        "roi_units": float(settled["realized_profit_units"].mean()) if not settled.empty else None,
        "profit_eur": total_profit_eur,
        "roi_eur": total_profit_eur / total_stake if total_stake > 0.0 else None,
        "hit_rate": float((settled["result_status"] == "won").mean()) if not settled.empty else None,
    }


def update_ledger_file(ledger_path: Path, evaluated: pd.DataFrame) -> None:
    if "snapshot_key" not in evaluated.columns:
        raise ValueError("Cannot update ledger without snapshot_key column")

    ledger = pd.read_csv(ledger_path)
    update_cols = [
        "snapshot_key",
        "result_status",
        "actual_result",
        "actual_outcome",
        "actual_home_score",
        "actual_away_score",
        "match_found",
        "realized_profit_units",
        "realized_profit",
    ]
    updates = evaluated[update_cols].drop_duplicates(subset=["snapshot_key"], keep="last")
    merged = ledger.merge(updates, on="snapshot_key", how="left", suffixes=("", "_new"))

    for column in update_cols[1:]:
        new_col = f"{column}_new"
        if column not in merged.columns:
            merged[column] = pd.NA
        if new_col in merged.columns:
            merged[column] = merged[new_col].combine_first(merged[column])
            merged = merged.drop(columns=[new_col])

    merged.to_csv(ledger_path, index=False)


def main() -> None:
    args = parse_args()
    ledger_path = resolve_path(args.ledger)
    data_dir = resolve_path(args.data_dir)
    output_path = resolve_path(args.output)
    summary_path = resolve_path(args.summary_output)

    freeze_date = normalize_date(args.freeze_date)
    as_of_date = (
        normalize_date(args.as_of_date)
        if args.as_of_date
        else normalize_date(pd.Timestamp.today())
    )

    ledger = pd.read_csv(ledger_path)
    portfolio_name = None if args.all_portfolios else args.portfolio
    recommended_only = not args.include_trends
    prepared = prepare_ledger(
        ledger,
        freeze_date,
        portfolio_name=portfolio_name,
        recommended_only=recommended_only,
    )
    results = load_home_results(data_dir)
    evaluated = evaluate_rows(prepared, results, as_of_date=as_of_date)
    summary = build_summary(
        evaluated,
        freeze_date=freeze_date.date().isoformat(),
        as_of_date=as_of_date.date().isoformat(),
        portfolio_name=portfolio_name,
        recommended_only=recommended_only,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    evaluated.to_csv(output_path, index=False)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if args.update_ledger:
        update_ledger_file(ledger_path, evaluated)

    print(summary | {"output": str(output_path), "summary_output": str(summary_path)})


if __name__ == "__main__":
    main()
