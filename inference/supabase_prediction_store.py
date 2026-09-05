from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from inference.live_tracking import canonical_snapshot_keys, canonicalize_tracking_rows
from inference.kickoff_time import paris_iso


DEFAULT_LEDGER = Path(__file__).resolve().parent / "output" / "live_portfolio_bet_log.csv"
DEFAULT_STATUS = Path(__file__).resolve().parent / "output" / "prediction_store_status.json"
TABLE = "prediction_history"
REMOTE_COLUMNS = [
    "snapshot_key",
    "fixture_id",
    "kickoff_utc",
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
    "actual_result",
    "actual_outcome",
    "actual_home_score",
    "actual_away_score",
    "match_found",
    "realized_profit_units",
]
BOOLEAN_COLUMNS = {"recommended", "match_found"}
INTEGER_COLUMNS = {"train_max_season", "actual_home_score", "actual_away_score"}


def configuration() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )
    return url, key


def request_headers(key: str, *, upsert: bool = False) -> dict[str, str]:
    headers = {"apikey": key, "Accept": "application/json"}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {key}"
    if upsert:
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    return headers


def write_status(path: Path, *, backend: str, configured: bool, rows: int, action: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "backend": backend,
                "configured": configured,
                "rows": rows,
                "lastAction": action,
                "lastSyncAt": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def clean_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def clean_boolean(value: Any) -> bool | None:
    value = clean_value(value)
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {
        "0",
        "0.0",
        "false",
        "no",
        "non",
        "none",
        "nan",
        "<na>",
    }


def clean_integer(value: Any) -> int | None:
    value = clean_value(value)
    if value is None or str(value).strip() == "":
        return None
    return int(float(value))


def remote_records(local: pd.DataFrame) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in local.to_dict(orient="records"):
        record = {column: clean_value(row.get(column)) for column in REMOTE_COLUMNS}
        for column in BOOLEAN_COLUMNS:
            record[column] = clean_boolean(record.get(column))
        for column in INTEGER_COLUMNS:
            record[column] = clean_integer(record.get(column))
        record["recommended"] = bool(record.get("recommended"))
        record["result_status"] = record.get("result_status") or "pending"
        record["date"] = paris_iso(record["date"])
        record["fixture_id"] = str(record.get("fixture_id") or "").strip() or None
        raw_kickoff = str(record.get("kickoff_utc") or "").strip()
        record["kickoff_utc"] = (
            pd.to_datetime(raw_kickoff, errors="raise", utc=True).isoformat()
            if raw_kickoff
            else None
        )
        payload.append(record)
    return payload


def recommended_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if "recommended" not in frame.columns:
        return frame.iloc[0:0].copy()
    mask = frame["recommended"].map(lambda value: bool(clean_boolean(value))).astype(bool)
    return frame.loc[mask].copy()


def portfolio_rows(frame: pd.DataFrame, portfolio_name: str = "") -> pd.DataFrame:
    if not portfolio_name:
        return frame.copy()
    if "portfolio_name" not in frame.columns:
        return frame.iloc[0:0].copy()
    return frame.loc[frame["portfolio_name"].astype(str) == portfolio_name].copy()


def pull(
    ledger: Path,
    status_path: Path,
    *,
    portfolio_name: str = "",
    timeout: float = 30.0,
) -> int:
    url, key = configuration()
    if not url or not key:
        local_rows = len(pd.read_csv(ledger)) if ledger.exists() else 0
        write_status(status_path, backend="local", configured=False, rows=local_rows, action="pull")
        return local_rows

    params = {"select": ",".join(REMOTE_COLUMNS), "recommended": "eq.true", "order": "date.asc"}
    if portfolio_name:
        params["portfolio_name"] = f"eq.{portfolio_name}"
    response = requests.get(
        f"{url}/rest/v1/{TABLE}",
        headers=request_headers(key),
        params=params,
        timeout=timeout,
    )
    response.raise_for_status()
    rows = response.json()
    local = canonicalize_tracking_rows(pd.DataFrame(rows, columns=REMOTE_COLUMNS))
    # Switching the active portfolio must not erase other versions locally.
    if ledger.exists() and portfolio_name:
        existing = pd.read_csv(ledger)
        other = existing[existing.get("portfolio_name", pd.Series("", index=existing.index)).astype(str) != portfolio_name]
        local = pd.concat([other, local], ignore_index=True)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    local.to_csv(ledger, index=False)
    write_status(status_path, backend="supabase", configured=True, rows=len(local), action="pull")
    return len(local)


def delete_superseded_remote_rows(
    url: str,
    key: str,
    canonical_keys: set[str],
    *,
    portfolio_name: str = "",
    timeout: float,
) -> int:
    params = {
        "select": "snapshot_key,portfolio_name,date,league,team_name,opponent_name,selected_outcome",
        "recommended": "eq.true",
    }
    if portfolio_name:
        params["portfolio_name"] = f"eq.{portfolio_name}"
    response = requests.get(
        f"{url}/rest/v1/{TABLE}",
        headers=request_headers(key),
        params=params,
        timeout=timeout,
    )
    response.raise_for_status()
    remote = pd.DataFrame(response.json())
    if remote.empty:
        return 0

    remote["canonical_key"] = canonical_snapshot_keys(remote)
    obsolete = remote.loc[
        (remote["snapshot_key"].astype(str) != remote["canonical_key"].astype(str))
        & remote["canonical_key"].isin(canonical_keys),
        "snapshot_key",
    ].astype(str)
    deleted = 0
    for snapshot_key in dict.fromkeys(obsolete):
        delete_response = requests.delete(
            f"{url}/rest/v1/{TABLE}",
            headers=request_headers(key),
            params={"snapshot_key": f"eq.{snapshot_key}"},
            timeout=timeout,
        )
        delete_response.raise_for_status()
        deleted += 1
    return deleted


def push(
    ledger: Path,
    status_path: Path,
    *,
    portfolio_name: str = "",
    timeout: float = 30.0,
) -> int:
    url, key = configuration()
    local = pd.read_csv(ledger) if ledger.exists() else pd.DataFrame(columns=REMOTE_COLUMNS)
    local = canonicalize_tracking_rows(portfolio_rows(recommended_rows(local), portfolio_name))
    if not url or not key:
        write_status(status_path, backend="local", configured=False, rows=len(local), action="push")
        return len(local)
    if local.empty:
        write_status(status_path, backend="supabase", configured=True, rows=0, action="push")
        return 0

    payload = remote_records(local)

    response = requests.post(
        f"{url}/rest/v1/{TABLE}",
        headers=request_headers(key, upsert=True),
        params={"on_conflict": "snapshot_key"},
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    delete_superseded_remote_rows(
        url,
        key,
        {str(row["snapshot_key"]) for row in payload},
        portfolio_name=portfolio_name,
        timeout=timeout,
    )
    write_status(status_path, backend="supabase", configured=True, rows=len(payload), action="push")
    return len(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronise la mémoire des prévisions avec Supabase.")
    parser.add_argument("action", choices=["pull", "push"])
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--status-output", default=str(DEFAULT_STATUS))
    parser.add_argument("--portfolio", default="")
    args = parser.parse_args()

    ledger = Path(args.ledger).resolve()
    status_path = Path(args.status_output).resolve()
    rows = (
        pull(ledger, status_path, portfolio_name=args.portfolio)
        if args.action == "pull"
        else push(ledger, status_path, portfolio_name=args.portfolio)
    )
    backend = "supabase" if all(configuration()) else "local"
    print({"action": args.action, "backend": backend, "rows": rows})


if __name__ == "__main__":
    main()
