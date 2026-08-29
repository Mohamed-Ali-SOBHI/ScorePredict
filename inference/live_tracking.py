from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from data_pipeline.market_data import normalize_team_name
from inference.kickoff_time import (
    coerce_paris_timestamp,
    paris_date_key,
    paris_iso,
    paris_naive,
)


TRACKING_COLUMNS = [
    "snapshot_key",
    "prediction_generated_at_utc",
    "portfolio_name",
    "date",
    "league",
    "team_name",
    "opponent_name",
    "selected_outcome",
    "selected_odds",
    "predicted_probability",
    "raw_model_probability",
    "market_probability",
    "edge",
    "value_score",
    "expected_value",
    "raw_expected_value",
    "probability_note",
    "train_max_season",
    "strategy_names",
    "stake_eur",
    "recommended",
    "result_status",
    "closing_selected_odds",
    "realized_profit",
]


def _recommended_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"", "0", "0.0", "false", "no", "none", "nan", "<na>"}


def canonical_snapshot_keys(frame: pd.DataFrame) -> pd.Series:
    required = {
        "portfolio_name",
        "date",
        "league",
        "team_name",
        "opponent_name",
        "selected_outcome",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Cannot build canonical tracking keys without: {', '.join(missing)}")

    date_keys = frame["date"].map(paris_date_key)
    date_keys = date_keys.mask(date_keys == "", frame["date"].astype(str).str.slice(0, 10))
    home = frame["team_name"].map(normalize_team_name)
    away = frame["opponent_name"].map(normalize_team_name)
    return (
        frame["portfolio_name"].astype(str)
        + "|"
        + date_keys.astype(str)
        + "|"
        + frame["league"].astype(str)
        + "|"
        + home.astype(str)
        + "|"
        + away.astype(str)
        + "|"
        + frame["selected_outcome"].astype(str)
    )


def canonicalize_tracking_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    canonical = frame.copy()
    required = {
        "portfolio_name",
        "date",
        "league",
        "team_name",
        "opponent_name",
        "selected_outcome",
    }
    if not required.issubset(canonical.columns):
        if "snapshot_key" in canonical.columns:
            return canonical.drop_duplicates(subset=["snapshot_key"], keep="first").reset_index(drop=True)
        return canonical
    canonical["snapshot_key"] = canonical_snapshot_keys(canonical)
    status_priority = {
        "won": 3,
        "lost": 3,
        "void": 3,
        "pending_data_refresh": 2,
        "unmatched": 1,
        "pending": 0,
    }
    canonical["_status_priority"] = canonical.get(
        "result_status",
        pd.Series("pending", index=canonical.index),
    ).map(status_priority).fillna(0)
    generated_at = pd.to_datetime(
        canonical.get("prediction_generated_at_utc"),
        errors="coerce",
        utc=True,
        format="mixed",
    )
    canonical["_generated_at"] = generated_at
    canonical = canonical.sort_values(
        ["snapshot_key", "_status_priority", "_generated_at"],
        ascending=[True, False, True],
        na_position="last",
    )
    canonical = canonical.drop_duplicates(subset=["snapshot_key"], keep="first")
    return canonical.drop(columns=["_status_priority", "_generated_at"]).reset_index(drop=True)


def build_tracking_rows(bets: pd.DataFrame, *, portfolio_name: str) -> pd.DataFrame:
    if bets.empty:
        return bets.copy()

    tracked = bets.copy()
    tracked["date"] = tracked["date"].map(paris_iso)
    tracked["prediction_generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    tracked["portfolio_name"] = portfolio_name
    tracked["snapshot_key"] = canonical_snapshot_keys(tracked)
    recommended = tracked.get("recommended_bet", pd.Series(False, index=tracked.index))
    tracked["recommended"] = recommended.map(_recommended_value)
    tracked["result_status"] = "pending"
    tracked["closing_selected_odds"] = pd.NA
    tracked["realized_profit"] = pd.NA
    for column in TRACKING_COLUMNS:
        if column not in tracked.columns:
            tracked[column] = pd.NA
    return tracked[TRACKING_COLUMNS].copy()


def refresh_pending_fixture_dates(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    """Refresh kickoff times without rewriting the original betting decision."""
    required = {
        "portfolio_name",
        "date",
        "league",
        "team_name",
        "opponent_name",
        "selected_outcome",
    }
    if existing.empty or incoming.empty:
        return existing.copy()
    if not required.issubset(existing.columns) or not required.issubset(incoming.columns):
        return existing.copy()

    refreshed = existing.copy()
    updates = incoming.copy()
    refreshed["_canonical_key"] = canonical_snapshot_keys(refreshed)
    updates["_canonical_key"] = canonical_snapshot_keys(updates)
    updates["_generated_at"] = pd.to_datetime(
        updates.get("prediction_generated_at_utc"),
        errors="coerce",
        utc=True,
        format="mixed",
    )
    updates = updates.sort_values("_generated_at", na_position="first")
    latest_dates = updates.drop_duplicates("_canonical_key", keep="last").set_index("_canonical_key")["date"].map(paris_iso)
    statuses = refreshed.get("result_status", pd.Series("pending", index=refreshed.index))
    can_refresh = ~statuses.astype(str).str.lower().isin({"won", "lost", "void"})
    has_update = refreshed["_canonical_key"].isin(latest_dates.index)
    refreshed.loc[can_refresh & has_update, "date"] = refreshed.loc[
        can_refresh & has_update, "_canonical_key"
    ].map(latest_dates)
    return refreshed.drop(columns="_canonical_key")


def refresh_pending_fixture_dates_from_catalog(
    existing: pd.DataFrame,
    catalog: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """Repair pending kickoff times from a verified fixture catalog.

    This deliberately ignores whether the bet is still recommended at the
    latest odds. Once published, its kickoff must follow the fixture itself.
    """
    required_existing = {"date", "league", "team_name", "opponent_name"}
    if existing.empty or catalog.empty or not required_existing.issubset(existing.columns):
        return existing.copy(), 0

    date_column = "official_date" if "official_date" in catalog.columns else "date"
    if date_column not in catalog.columns or "league" not in catalog.columns:
        return existing.copy(), 0

    fixtures = catalog.copy()
    if {"home_team", "away_team"}.issubset(fixtures.columns):
        fixtures["_home_norm"] = fixtures["home_team"].map(normalize_team_name)
        fixtures["_away_norm"] = fixtures["away_team"].map(normalize_team_name)
    elif {"home_team_norm", "away_team_norm"}.issubset(fixtures.columns):
        fixtures["_home_norm"] = fixtures["home_team_norm"].astype(str)
        fixtures["_away_norm"] = fixtures["away_team_norm"].astype(str)
    else:
        return existing.copy(), 0

    fixtures["_catalog_date"] = fixtures[date_column].map(coerce_paris_timestamp)
    fixtures = fixtures[fixtures["_catalog_date"].notna()].copy()
    if fixtures.empty:
        return existing.copy(), 0

    refreshed = existing.copy()
    statuses = refreshed.get("result_status", pd.Series("pending", index=refreshed.index))
    terminal = statuses.fillna("pending").astype(str).str.lower().isin({"won", "lost", "void"})
    refreshed_count = 0

    for index in refreshed.index[~terminal]:
        row = refreshed.loc[index]
        candidates = fixtures[
            (fixtures["league"].astype(str) == str(row.get("league")))
            & (fixtures["_home_norm"] == normalize_team_name(row.get("team_name")))
            & (fixtures["_away_norm"] == normalize_team_name(row.get("opponent_name")))
        ].copy()
        if candidates.empty:
            continue

        current_date = coerce_paris_timestamp(row.get("date"))
        if pd.notna(current_date):
            candidates["_distance"] = (candidates["_catalog_date"] - current_date).abs()
            candidates = candidates[candidates["_distance"] <= pd.Timedelta(days=2)]
        if candidates.empty:
            continue

        selected = candidates.sort_values("_distance" if "_distance" in candidates else "_catalog_date").iloc[0]
        corrected_date = selected[date_column]
        corrected_paris = coerce_paris_timestamp(corrected_date)
        if pd.notna(current_date) and pd.notna(corrected_paris) and current_date == corrected_paris:
            continue
        refreshed.at[index, "date"] = paris_iso(corrected_date)
        refreshed_count += 1

    return refreshed, refreshed_count


def append_tracking_rows(tracking_rows: pd.DataFrame, ledger_path: Path) -> None:
    if tracking_rows.empty:
        return

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger_path.exists():
        existing = pd.read_csv(ledger_path)
        existing = refresh_pending_fixture_dates(existing, tracking_rows)
        combined = pd.concat([existing, tracking_rows], ignore_index=True)
        # Une prévision publiée reste figée : les nouveaux calculs ne réécrivent
        # ni son choix, ni sa cote, ni un résultat déjà vérifié.
        combined = canonicalize_tracking_rows(combined)
    else:
        combined = canonicalize_tracking_rows(tracking_rows)
    combined.to_csv(ledger_path, index=False)
