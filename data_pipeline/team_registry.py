from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REGISTRY_FILENAME = "team_registry.json"
EXPECTED_TEAM_COUNTS = {
    "EPL": 20,
    "La_liga": 20,
    "Bundesliga": 18,
    "Serie_A": 20,
    "Ligue_1": 18,
}


def registry_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / REGISTRY_FILENAME


def records_from_understat(data: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for season_key, teams in data.items():
        league, season_text = season_key.rsplit(" ", maxsplit=1)
        for team_id, team_data in teams.items():
            records.append(
                {
                    "league": league,
                    "season": int(season_text),
                    "team_id": str(team_id),
                    "team_name": str(team_data.get("title", "")).strip(),
                }
            )
    return sorted(records, key=lambda row: (row["season"], row["league"], row["team_name"]))


def write_records(
    records: list[dict[str, Any]],
    data_dir: str | Path = "Data",
    *,
    source: str,
) -> Path:
    target = registry_path(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = read_registry(data_dir)
    incoming_groups = {(int(row["season"]), str(row["league"])) for row in records}
    preserved = [
        row
        for row in existing.get("teams", [])
        if (int(row.get("season", -1)), str(row.get("league", ""))) not in incoming_groups
    ]
    merged = preserved + records
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "teams": sorted(merged, key=lambda row: (int(row["season"]), row["league"], row["team_name"])),
    }
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def write_registry(data: dict[str, dict[str, Any]], data_dir: str | Path = "Data") -> Path:
    records = records_from_understat(data)
    target = registry_path(data_dir)
    if not records and target.exists():
        return target
    return write_records(records, data_dir, source="understat")


def read_registry(data_dir: str | Path) -> dict[str, Any]:
    path = registry_path(data_dir)
    if not path.exists():
        return {"generated_at": None, "teams": []}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def audit_registry(payload: dict[str, Any], season: int) -> dict[str, Any]:
    teams = [row for row in payload.get("teams", []) if int(row.get("season", -1)) == season]
    leagues: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for league, expected in EXPECTED_TEAM_COUNTS.items():
        rows = [row for row in teams if row.get("league") == league]
        ids = [str(row.get("team_id", "")) for row in rows]
        names = [str(row.get("team_name", "")).strip() for row in rows]
        ok = len(rows) == expected and len(set(ids)) == expected and len(set(names)) == expected and all(names)
        leagues[league] = {
            "expected": expected,
            "actual": len(rows),
            "status": "ok" if ok else "error",
            "teams": sorted(names),
        }
        if not ok:
            problems.append(f"{league}: {len(rows)} club(s) trouvé(s), {expected} attendu(s)")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_generated_at": payload.get("generated_at"),
        "season": season,
        "status": "ok" if not problems else "error",
        "total_teams": len(teams),
        "expected_total": sum(EXPECTED_TEAM_COUNTS.values()),
        "leagues": leagues,
        "problems": problems,
    }
