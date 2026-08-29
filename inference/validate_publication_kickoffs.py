from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from data_pipeline.market_data import normalize_team_name
from inference.kickoff_time import paris_timestamp


def validate_publication_kickoffs(
    snapshot: dict[str, Any],
    fixtures: pd.DataFrame,
    *,
    tolerance_minutes: int = 1,
) -> None:
    required = {"date", "league", "home_team", "away_team"}
    missing = sorted(required - set(fixtures.columns))
    if missing:
        raise ValueError(f"Fixture catalog is missing: {', '.join(missing)}")

    catalog = fixtures.copy()
    catalog["_home_norm"] = catalog["home_team"].map(normalize_team_name)
    catalog["_away_norm"] = catalog["away_team"].map(normalize_team_name)
    catalog["_kickoff"] = catalog["date"].map(paris_timestamp)
    tolerance = pd.Timedelta(minutes=tolerance_minutes)
    errors: list[str] = []

    for prediction in snapshot.get("predictions", []) or []:
        label = f"{prediction.get('homeTeam')} - {prediction.get('awayTeam')}"
        raw_published_date = prediction.get("date")
        parsed_published_date = pd.Timestamp(raw_published_date)
        if parsed_published_date.tzinfo is None:
            errors.append(f"{label}: fuseau horaire absent de la date publiée")
            continue
        candidates = catalog[
            (catalog["league"].astype(str) == str(prediction.get("league")))
            & (catalog["_home_norm"] == normalize_team_name(prediction.get("homeTeam")))
            & (catalog["_away_norm"] == normalize_team_name(prediction.get("awayTeam")))
        ].copy()
        if candidates.empty:
            errors.append(f"{label}: absent du calendrier vérifié")
            continue

        published = paris_timestamp(raw_published_date)
        candidates["_distance"] = (candidates["_kickoff"] - published).abs()
        nearest = candidates.sort_values("_distance").iloc[0]
        if nearest["_distance"] > tolerance:
            errors.append(
                f"{label}: heure publiée {published.isoformat()} au lieu de "
                f"{nearest['_kickoff'].isoformat()}"
            )

    if errors:
        raise ValueError("Publication bloquée — horaires incohérents : " + "; ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description="Bloque un dashboard dont les horaires ne sont pas officiels.")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--tolerance-minutes", type=int, default=1)
    args = parser.parse_args()

    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8-sig"))
    fixtures = pd.read_csv(args.fixtures)
    validate_publication_kickoffs(snapshot, fixtures, tolerance_minutes=args.tolerance_minutes)
    print({"status": "ok", "publishedKickoffsVerified": len(snapshot.get("predictions", []) or [])})


if __name__ == "__main__":
    main()
