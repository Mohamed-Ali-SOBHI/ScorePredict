from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


DEFAULT_LEDGER = Path(__file__).resolve().parent / "output" / "live_portfolio_bet_log.csv"
DEFAULT_STATUS = Path(__file__).resolve().parent / "output" / "prediction_store_status.json"
TABLE = "prediction_history"
REMOTE_COLUMNS = [
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
        payload.append(record)
    return payload


def recommended_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if "recommended" not in frame.columns:
        return frame.iloc[0:0].copy()
    mask = frame["recommended"].map(lambda value: bool(clean_boolean(value))).astype(bool)
    return frame.loc[mask].copy()


def pull(ledger: Path, status_path: Path, *, timeout: float = 30.0) -> int:
    url, key = configuration()
    if not url or not key:
        local_rows = len(pd.read_csv(ledger)) if ledger.exists() else 0
        write_status(status_path, backend="local", configured=False, rows=local_rows, action="pull")
        return local_rows

    response = requests.get(
        f"{url}/rest/v1/{TABLE}",
        headers=request_headers(key),
        params={"select": ",".join(REMOTE_COLUMNS), "recommended": "eq.true", "order": "date.asc"},
        timeout=timeout,
    )
    response.raise_for_status()
    rows = response.json()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=REMOTE_COLUMNS).to_csv(ledger, index=False)
    write_status(status_path, backend="supabase", configured=True, rows=len(rows), action="pull")
    return len(rows)


def push(ledger: Path, status_path: Path, *, timeout: float = 30.0) -> int:
    url, key = configuration()
    local = pd.read_csv(ledger) if ledger.exists() else pd.DataFrame(columns=REMOTE_COLUMNS)
    local = recommended_rows(local)
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
    write_status(status_path, backend="supabase", configured=True, rows=len(payload), action="push")
    return len(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronise la mémoire des prévisions avec Supabase.")
    parser.add_argument("action", choices=["pull", "push"])
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--status-output", default=str(DEFAULT_STATUS))
    args = parser.parse_args()

    ledger = Path(args.ledger).resolve()
    status_path = Path(args.status_output).resolve()
    rows = pull(ledger, status_path) if args.action == "pull" else push(ledger, status_path)
    backend = "supabase" if all(configuration()) else "local"
    print({"action": args.action, "backend": backend, "rows": rows})


if __name__ == "__main__":
    main()
