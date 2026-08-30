from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from inference.sportytrader_client import infer_season
from inference.supabase_prediction_store import configuration, request_headers


TABLE = "fixture_registry"
DEFAULT_FIXTURES = Path(__file__).resolve().parent / "output" / "sportytrader_upcoming_portfolio_odds.csv"
DEFAULT_STATUS = Path(__file__).resolve().parent / "output" / "fixture_store_status.json"
REMOTE_COLUMNS = [
    "fixture_id",
    "league",
    "season",
    "home_team",
    "away_team",
    "kickoff_utc",
    "home_win_odds_open",
    "draw_odds_open",
    "away_win_odds_open",
    "schedule_source",
    "odds_source",
    "updated_at",
]


def _clean(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def fixture_records(fixtures: pd.DataFrame) -> list[dict[str, Any]]:
    required = {
        "fixture_id",
        "league",
        "home_team",
        "away_team",
        "kickoff_utc",
        "schedule_source",
    }
    missing = sorted(required - set(fixtures.columns))
    if missing:
        raise ValueError(f"Fixture registry input is missing: {', '.join(missing)}")

    records: list[dict[str, Any]] = []
    sync_time = datetime.now(timezone.utc).isoformat()
    for row in fixtures.to_dict(orient="records"):
        kickoff = pd.to_datetime(row.get("kickoff_utc"), errors="raise", utc=True)
        raw_season = _clean(row.get("season"))
        raw_odds_source = _clean(row.get("source")) or _clean(row.get("odds_source"))
        record = {column: _clean(row.get(column)) for column in REMOTE_COLUMNS}
        record.update(
            {
                "fixture_id": str(row["fixture_id"]).strip(),
                "league": str(row["league"]).strip(),
                "season": int(raw_season) if raw_season is not None else infer_season(kickoff),
                "home_team": str(row["home_team"]).strip(),
                "away_team": str(row["away_team"]).strip(),
                "kickoff_utc": kickoff.isoformat(),
                "schedule_source": str(row["schedule_source"]).strip(),
                "odds_source": str(raw_odds_source).strip() if raw_odds_source else None,
                "updated_at": sync_time,
            }
        )
        if not record["fixture_id"]:
            raise ValueError("fixture_id cannot be empty")
        records.append(record)
    return records


def write_status(path: Path, *, configured: bool, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "backend": "supabase" if configured else "local",
                "configured": configured,
                "rows": rows,
                "lastAction": "push",
                "lastSyncAt": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def push(fixtures_path: Path, status_path: Path, *, timeout: float = 30.0) -> int:
    fixtures = pd.read_csv(fixtures_path) if fixtures_path.exists() else pd.DataFrame()
    payload = fixture_records(fixtures) if not fixtures.empty else []
    url, key = configuration()
    configured = bool(url and key)
    if not configured or not payload:
        write_status(status_path, configured=configured, rows=len(payload))
        return len(payload)

    response = requests.post(
        f"{url}/rest/v1/{TABLE}",
        headers=request_headers(key, upsert=True),
        params={"on_conflict": "fixture_id"},
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    write_status(status_path, configured=True, rows=len(payload))
    return len(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Enregistre le calendrier canonique dans Supabase.")
    parser.add_argument("push", choices=["push"])
    parser.add_argument("--fixtures", default=str(DEFAULT_FIXTURES))
    parser.add_argument("--status-output", default=str(DEFAULT_STATUS))
    args = parser.parse_args()

    rows = push(Path(args.fixtures).resolve(), Path(args.status_output).resolve())
    print({"action": "push", "table": TABLE, "rows": rows})


if __name__ == "__main__":
    main()
