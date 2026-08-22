from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from data_pipeline.market_data import normalize_team_name


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

    dates = pd.to_datetime(frame["date"], errors="coerce", utc=True, format="mixed")
    date_keys = dates.dt.strftime("%Y-%m-%d")
    date_keys = date_keys.fillna(frame["date"].astype(str).str.slice(0, 10))
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
    latest_dates = updates.drop_duplicates("_canonical_key", keep="last").set_index("_canonical_key")["date"]
    statuses = refreshed.get("result_status", pd.Series("pending", index=refreshed.index))
    can_refresh = ~statuses.astype(str).str.lower().isin({"won", "lost", "void"})
    has_update = refreshed["_canonical_key"].isin(latest_dates.index)
    refreshed.loc[can_refresh & has_update, "date"] = refreshed.loc[
        can_refresh & has_update, "_canonical_key"
    ].map(latest_dates)
    return refreshed.drop(columns="_canonical_key")


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
