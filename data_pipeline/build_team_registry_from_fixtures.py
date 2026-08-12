from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pandas as pd

from data_pipeline.market_data import normalize_team_name
from data_pipeline.team_registry import EXPECTED_TEAM_COUNTS, audit_registry, write_records


def stable_new_team_id(league: str, normalized_name: str) -> str:
    digest = hashlib.sha1(f"{league}:{normalized_name}".encode("utf-8")).hexdigest()[:12]
    return f"new-{digest}"


def build_records(fixtures: pd.DataFrame, historical: pd.DataFrame, season: int) -> list[dict[str, object]]:
    history = historical.copy()
    history["team_name_norm"] = history["team_name"].map(normalize_team_name)
    latest = history.sort_values(["season", "date"]).groupby(
        ["league", "team_name_norm"], as_index=False
    ).tail(1)
    lookup = {
        (row.league, row.team_name_norm): {"team_id": str(row.team_id), "team_name": row.team_name}
        for row in latest.itertuples(index=False)
    }

    clubs: set[tuple[str, str, str]] = set()
    for row in fixtures.itertuples(index=False):
        clubs.add((str(row.league), normalize_team_name(row.home_team), str(row.home_team)))
        clubs.add((str(row.league), normalize_team_name(row.away_team), str(row.away_team)))

    records: list[dict[str, object]] = []
    for league, normalized_name, source_name in sorted(clubs):
        known = lookup.get((league, normalized_name))
        records.append(
            {
                "league": league,
                "season": season,
                "team_id": known["team_id"] if known else stable_new_team_id(league, normalized_name),
                "team_name": known["team_name"] if known else source_name,
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the current-season club registry from upcoming fixtures.")
    parser.add_argument("--fixtures-csv", required=True)
    parser.add_argument("--data-dir", default="Data")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--historical-dataset", default="train/dataset_home.csv")
    args = parser.parse_args()

    fixtures = pd.read_csv(args.fixtures_csv)
    required = {"league", "home_team", "away_team"}
    missing = required.difference(fixtures.columns)
    if missing:
        raise ValueError(f"Fixtures file is missing columns: {sorted(missing)}")

    home = pd.read_csv(
        args.historical_dataset,
        usecols=["date", "league", "season", "team_id", "team_name", "away_team_id", "away_team_name"],
    )
    away = home[["date", "league", "season", "away_team_id", "away_team_name"]].rename(
        columns={"away_team_id": "team_id", "away_team_name": "team_name"}
    )
    historical = pd.concat(
        [home[["date", "league", "season", "team_id", "team_name"]], away],
        ignore_index=True,
    )
    historical["date"] = pd.to_datetime(historical["date"])
    records = build_records(fixtures, historical, args.season)
    candidate = {"generated_at": None, "teams": records}
    audit = audit_registry(candidate, args.season)
    if audit["status"] != "ok":
        details = "; ".join(audit["problems"])
        raise SystemExit(f"Registre incomplet à partir des calendriers : {details}")

    path = write_records(records, args.data_dir, source="upcoming_fixtures")
    print(
        {
            "season": args.season,
            "clubs": len(records),
            "expected": sum(EXPECTED_TEAM_COUNTS.values()),
            "registry": str(Path(path).resolve()),
        }
    )


if __name__ == "__main__":
    main()
