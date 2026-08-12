from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.market_data import CLOSING_MARKET_COLS, load_market_data, normalize_team_name


REQUIRED_BET_COLUMNS = {
    "date",
    "league",
    "season",
    "team_name",
    "opponent_name",
}


def prepare_bets_for_closing_match(bets_df: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(REQUIRED_BET_COLUMNS - set(bets_df.columns))
    if missing:
        raise ValueError(f"Missing columns for CLV matching: {', '.join(missing)}")

    bet_ids = pd.Series(range(len(bets_df)), name="_bet_row_id")
    prepared = pd.concat([bet_ids, bets_df.reset_index(drop=True).copy()], axis=1)
    prepared["date"] = pd.to_datetime(prepared["date"])
    prepared["season"] = pd.to_numeric(prepared["season"], errors="raise").astype(int)
    prepared["bet_match_date"] = prepared["date"].dt.normalize()
    prepared["home_team_norm"] = prepared["team_name"].map(normalize_team_name)
    prepared["away_team_norm"] = prepared["opponent_name"].map(normalize_team_name)
    return prepared


def match_bets_to_closing_market(
    bets_df: pd.DataFrame,
    *,
    max_date_diff_days: int = 7,
) -> pd.DataFrame:
    if bets_df.empty:
        return bets_df.copy()

    prepared = prepare_bets_for_closing_match(bets_df)
    refreshed_market_cols = [
        "closing_market_match_date",
        "closing_match_date_diff_days",
        "closing_match_found",
        *CLOSING_MARKET_COLS,
    ]
    prepared = prepared.drop(
        columns=[column for column in refreshed_market_cols if column in prepared.columns],
        errors="ignore",
    )
    market = load_market_data(
        set(prepared["league"]),
        set(prepared["season"]),
        include_closing=True,
    )

    merge_keys = ["league", "season", "home_team_norm", "away_team_norm"]
    exact = prepared.merge(market, on=merge_keys, how="left", suffixes=("", "_market"))
    exact = exact[exact["bet_match_date"] == exact["market_match_date"]].copy()
    exact["closing_match_date_diff_days"] = 0

    matched_ids = set(exact["_bet_row_id"].tolist())
    unmatched = prepared[~prepared["_bet_row_id"].isin(matched_ids)].copy()

    fallback = unmatched.merge(market, on=merge_keys, how="left", suffixes=("", "_market"))
    fallback["closing_match_date_diff_days"] = (
        fallback["market_match_date"] - fallback["bet_match_date"]
    ).dt.days.abs()
    fallback = fallback[fallback["closing_match_date_diff_days"] <= max_date_diff_days].copy()
    fallback = fallback.sort_values(["_bet_row_id", "closing_match_date_diff_days", "market_match_date"])
    fallback = fallback.drop_duplicates(subset=["_bet_row_id"], keep="first")

    matched = pd.concat([exact, fallback], ignore_index=True, sort=False)
    matched = matched.drop_duplicates(subset=["_bet_row_id"], keep="first")
    matched = matched.rename(columns={"market_match_date": "closing_market_match_date"})

    closing_cols = ["_bet_row_id", "closing_market_match_date", "closing_match_date_diff_days"] + CLOSING_MARKET_COLS
    merged = prepared.merge(matched[closing_cols], on="_bet_row_id", how="left", validate="one_to_one")
    merged["closing_match_found"] = merged[CLOSING_MARKET_COLS].notna().all(axis=1)

    helper_cols = ["_bet_row_id", "bet_match_date", "home_team_norm", "away_team_norm"]
    return merged.drop(columns=helper_cols)
